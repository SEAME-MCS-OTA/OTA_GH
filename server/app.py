"""
OTA Server - Main Application
Flask REST API 서버
"""
import os
import logging
import hashlib
import shutil
from datetime import datetime

from flask import Flask, request, jsonify, send_file    # request: 클라이언트의 HTTP 요청 전체 
from flask_cors import CORS
from packaging import version
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect as sa_inspect, text

from config import Config
from models import db, Vehicle, Firmware, UpdateHistory
from mqtt_handler import MQTTHandler

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask 앱 초기화
app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

# 데이터베이스 초기화
db.init_app(app)

# MQTT 핸들러 (나중에 초기화)
mqtt_handler = None


def init_db():
    """데이터베이스 테이블 생성"""
    with app.app_context():
        try:
            db.create_all()
            ensure_schema_compatibility()
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise


def ensure_schema_compatibility():
    """기존 DB와 ORM 모델 간 스키마 차이를 최소한으로 보정"""
    inspector = sa_inspect(db.engine)
    table_names = set(inspector.get_table_names())

    if 'update_history' not in table_names:
        return

    update_history_columns = {
        column['name'] for column in inspector.get_columns('update_history')
    }

    with db.engine.begin() as conn:
        if 'update_type' not in update_history_columns:
            conn.execute(text("ALTER TABLE update_history ADD COLUMN update_type VARCHAR(20)"))
            logger.info("Added missing column: update_history.update_type")

def init_mqtt():
    """MQTT 핸들러 초기화"""
    global mqtt_handler
    try:
        with app.app_context():
            mqtt_handler = MQTTHandler(app.app_context)
            mqtt_handler.connect()
            logger.info("MQTT handler initialized and connected")
    except Exception as e:
        logger.error(f"Failed to initialize MQTT handler: {e}")
        logger.warning("Server will run without MQTT support")

@app.before_request
def before_request():
    """첫 요청 시 MQTT 초기화"""
    global mqtt_handler
    if mqtt_handler is None:
        init_mqtt()

def compare_versions(v1: str, v2: str) -> int:
    """
    버전 비교 (semver)
    
    Returns:
        -1: v1 < v2
         0: v1 == v2
         1: v1 > v2
    """
    try:
        ver1 = version.parse(v1)
        ver2 = version.parse(v2)
        
        if ver1 < ver2:
            return -1
        elif ver1 > ver2:
            return 1
        else:
            return 0
    except Exception as e:
        logger.warning(f"Version comparison error: {e}, falling back to string comparison")
        # Fallback to string comparison
        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0


def parse_bool(value, default: bool = False) -> bool:
    """문자열/폼 값을 불리언으로 변환"""
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


@app.route('/health', methods=['GET'])
def health_check():
    """서버의 헬스체크 엔드포인트"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'mqtt_connected': mqtt_handler.is_connected() if mqtt_handler else False
    }), 200


@app.route('/api/v1/update-check', methods=['GET'])
def update_check():
    """
    업데이트 확인 API
    
    Query Parameters:
        vehicle_id: 차량 ID (필수)
        current_version: 현재 버전 (필수)
    
    Response:
        {
            "update_available": true/false,
            "version": "1.0.1",
            "url": "http://localhost:8080/firmware/app_1.0.1.tar.gz",
            "sha256": "...",
            "size": 123456,
            "release_notes": "..."
        }
    """
    try:
        vehicle_id = request.args.get('vehicle_id')
        current_version = request.args.get('current_version')
        
        # 필수 파라미터 검증
        if not vehicle_id or not current_version:
            return jsonify({
                'error': 'Missing required parameters: vehicle_id, current_version'
            }), 400
        
        logger.info(f"Update check request from vehicle {vehicle_id}, version {current_version}")
        
        # Vehicle upsert (없으면 생성, 있으면 업데이트)
        vehicle = Vehicle.query.filter_by(vehicle_id=vehicle_id).first()
        if vehicle:
            vehicle.last_seen = datetime.utcnow()
            vehicle.current_version = current_version
        else:
            vehicle = Vehicle(
                vehicle_id=vehicle_id,
                current_version=current_version,
                status='idle'
            )
            db.session.add(vehicle)
            logger.info(f"New vehicle registered: {vehicle_id}")
        
        db.session.commit()
        
        # 최신 active 펌웨어 조회
        # 지금 당장은 단순히 가장 최신 버전만 제공
        latest_firmware = Firmware.query.filter_by(
            is_active=True
        ).order_by(Firmware.created_at.desc()).first()
        
        if not latest_firmware:
            logger.warning("No active firmware available")
            return jsonify({
                'update_available': False,
                'message': 'No firmware available'
            })
        
        # 버전 비교
        comparison = compare_versions(current_version, latest_firmware.version)
        
        if comparison < 0:  # current_version < latest_version
            # 업데이트 가능
            firmware_url = f"{request.url_root.rstrip('/')}/firmware/{latest_firmware.filename}"
            
            response = {
                'update_available': True,
                'version': latest_firmware.version,
                'url': firmware_url,
                'sha256': latest_firmware.sha256,
                'size': latest_firmware.file_size,
                'release_notes': latest_firmware.release_notes or ''
            }
            
            logger.info(
                f"Update available for {vehicle_id}: "
                f"{current_version} -> {latest_firmware.version}"
            )
            
            return jsonify(response)
        else:
            # 이미 최신 버전
            logger.info(f"Vehicle {vehicle_id} is up to date: {current_version}")
            return jsonify({
                'update_available': False,
                'current_version': current_version,
                'latest_version': latest_firmware.version
            })
    
    except Exception as e:
        logger.error(f"Error in update_check: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/v1/report', methods=['POST'])
def report_status():
    """
    업데이트 상태 리포트 API
    
    Request Body:
        {
            "vehicle_id": "vehicle_001",
            "target_version": "1.0.1",
            "status": "downloading|verifying|installing|completed|failed",
            "progress": 0-100,
            "message": "optional message"
        }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # 필수 필드 검증
        required_fields = ['vehicle_id', 'target_version', 'status']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        vehicle_id = data['vehicle_id']
        target_version = data['target_version']
        status = data['status']
        progress = data.get('progress', 0)
        message = data.get('message', '')
        
        # 유효한 status 값 검증
        valid_statuses = ['downloading', 'verifying', 'installing', 'completed', 'failed']
        if status not in valid_statuses:
            return jsonify({'error': f'Invalid status: {status}'}), 400
        
        logger.info(
            f"Status report from {vehicle_id}: {status} "
            f"({progress}%) for version {target_version}"
        )
        
        # Vehicle 조회 또는 생성
        vehicle = Vehicle.query.filter_by(vehicle_id=vehicle_id).first()
        if not vehicle:
            vehicle = Vehicle(vehicle_id=vehicle_id, status=status)
            db.session.add(vehicle)
        else:
            vehicle.status = status
            vehicle.last_seen = datetime.utcnow()
        
        # completed 상태면 current_version 업데이트
        if status == 'completed':
            vehicle.current_version = target_version
        
        # UpdateHistory 업데이트 또는 생성
        history = UpdateHistory.query.filter_by(
            vehicle_id=vehicle_id,
            target_version=target_version
        ).order_by(UpdateHistory.started_at.desc()).first()
        
        if history:
            history.status = status
            history.progress = progress
            history.message = message
            if status in ['completed', 'failed']:
                history.completed_at = datetime.utcnow()
        else:
            # 새 히스토리 생성
            # firmware_id 조회
            firmware = Firmware.query.filter_by(version=target_version).first()
            
            history = UpdateHistory(
                vehicle_id=vehicle_id,
                firmware_id=firmware.id if firmware else None,
                from_version=vehicle.current_version if status != 'completed' else None,
                target_version=target_version,
                status=status,
                progress=progress,
                message=message
            )
            db.session.add(history)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'vehicle_id': vehicle_id,
            'status': status,
            'progress': progress
        })
    
    except Exception as e:
        logger.error(f"Error in report_status: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/firmware/<filename>', methods=['GET'])
def download_firmware(filename):
    """
    펌웨어 파일 다운로드
    
    Args:
        filename: 펌웨어 파일명
    """
    try:
        firmware = Firmware.query.filter_by(filename=filename).first_or_404()

        return send_file(
            firmware.file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/gzip'
        )
    
    except Exception as e:
        logger.error(f"Error serving firmware: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/v1/admin/firmware', methods=['POST'])
def upload_firmware():
    """
    펌웨어 업로드 및 등록 (관리자용)
    
    Form Data:
        file: 펌웨어 파일
        version: 버전 (예: 1.0.1)
        release_notes: 릴리즈 노트 (선택)
        overwrite: 기존 버전/파일 덮어쓰기 여부 (선택, 기본 false)
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        version_str = (request.form.get('version') or '').strip()
        release_notes = request.form.get('release_notes', '')
        overwrite = parse_bool(request.form.get('overwrite'), default=False)
        
        if not version_str:
            return jsonify({'error': 'Version is required'}), 400
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # 파일명 생성
        filename = f"app_{version_str}.tar.gz"
        filepath = os.path.join(Config.FIRMWARE_DIR, filename)

        # 같은 버전이 이미 등록된 경우 기본적으로 거부
        existing_firmware = Firmware.query.filter_by(version=version_str).first()
        if existing_firmware and not overwrite:
            return jsonify({
                'error': (
                    f'Firmware version {version_str} already exists. '
                    f'Use overwrite=true to replace it.'
                ),
                'firmware': existing_firmware.to_dict()
            }), 409

        old_filepath = existing_firmware.file_path if existing_firmware else None

        # 파일 저장: overwrite=false일 때 기존 파일 덮어쓰기 방지
        if os.path.exists(filepath):
            if not overwrite:
                return jsonify({
                    'error': (
                        f'Firmware file {filename} already exists on server. '
                        f'Use overwrite=true to replace it.'
                    )
                }), 409
            os.remove(filepath)

        file.stream.seek(0)
        with open(filepath, 'wb') as fw:
            shutil.copyfileobj(file.stream, fw)
        
        if not os.path.exists(filepath):
            return jsonify({
                'error': 'Failed to save uploaded firmware file'
            }), 500
        
        # SHA256 계산
        sha256_hash = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                sha256_hash.update(chunk)
        
        sha256 = sha256_hash.hexdigest()
        file_size = os.path.getsize(filepath)

        # 기존 버전 파일 경로가 달라졌다면 잔여 파일 정리
        if (
            overwrite and
            old_filepath and
            old_filepath != filepath and
            os.path.exists(old_filepath)
        ):
            os.remove(old_filepath)
        
        # DB 반영 (신규 등록 또는 기존 버전 갱신)
        if existing_firmware:
            existing_firmware.filename = filename
            existing_firmware.file_path = filepath
            existing_firmware.file_size = file_size
            existing_firmware.sha256 = sha256
            existing_firmware.release_notes = release_notes
            existing_firmware.is_active = True
            firmware = existing_firmware
            status_code = 200
            logger.info(f"Firmware replaced: {version_str} ({filename})")
        else:
            firmware = Firmware(
                version=version_str,
                filename=filename,
                file_path=filepath, 
                file_size=file_size,
                sha256=sha256,
                release_notes=release_notes,
                is_active=True
            )
            db.session.add(firmware)
            status_code = 201
            logger.info(f"Firmware uploaded: {version_str} ({filename})")

        db.session.commit()

        return jsonify({
            'success': True,
            'updated': bool(existing_firmware),
            'firmware': firmware.to_dict()
        }), status_code

    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': f'Firmware version {version_str} already exists'
        }), 409
    
    except Exception as e:
        logger.error(f"Error uploading firmware: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route('/api/v1/admin/trigger-update', methods=['POST'])
def trigger_update():
    """
    특정 차량에 업데이트 명령 전송 (MQTT) -> 관리자가
    
    Request Body:
        {
            "vehicle_id": "vehicle_001",
            "version": "1.0.1"  # 선택적, 없으면 최신 버전
        }
    """
    try:
        data = request.get_json()
        
        if not data or 'vehicle_id' not in data:
            return jsonify({'error': 'vehicle_id is required'}), 400
        
        vehicle_id = data['vehicle_id']
        target_version = data.get('version')
        
        # 특정 버전 지정 안 되면 최신 active 버전 사용
        if target_version:
            firmware = Firmware.query.filter_by(
                version=target_version,
                is_active=True
            ).first()
        else:
            firmware = Firmware.query.filter_by(
                is_active=True
            ).order_by(Firmware.created_at.desc()).first()
        
        if not firmware:
            return jsonify({'error': 'No active firmware found'}), 404
        
        # 펌웨어 정보 구성
        firmware_url = f"{request.url_root.rstrip('/')}/firmware/{firmware.filename}"
        firmware_info = {
            'version': firmware.version,
            'url': firmware_url,
            'sha256': firmware.sha256,
            'size': firmware.file_size,
            'release_notes': firmware.release_notes or ''
        }
        
        # MQTT로 업데이트 명령 발행
        if mqtt_handler and mqtt_handler.publish_update_command(vehicle_id, firmware_info):
            logger.info(f"Update command sent to {vehicle_id}: {firmware.version}")
            return jsonify({
                'success': True,
                'vehicle_id': vehicle_id,
                'version': firmware.version
            })
        else:
            logger.error(f"Failed to send update command to {vehicle_id}")
            return jsonify({'error': 'Failed to send MQTT command'}), 500
    
    except Exception as e:
        logger.error(f"Error triggering update: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/v1/vehicles', methods=['GET'])
def list_vehicles():
    """차량 목록 조회"""
    try:
        vehicles = Vehicle.query.order_by(Vehicle.last_seen.desc()).all()
        return jsonify({
            'vehicles': [v.to_dict() for v in vehicles],
            'total': len(vehicles)
        })
    except Exception as e:
        logger.error(f"Error listing vehicles: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/v1/vehicles/<vehicle_id>', methods=['GET'])
def get_vehicle(vehicle_id):
    """특정 차량 기본 정보 조회"""
    try:
        vehicle = Vehicle.query.filter_by(vehicle_id=vehicle_id).first()
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        return jsonify(vehicle.to_dict()), 200

    except Exception as e:
        logger.error(f"Error getting vehicle: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/api/v1/firmware', methods=['GET'])
def list_firmware():
    """펌웨어 목록 조회"""
    try:
        active_only = request.args.get('active_only', 'false').lower() == 'true'
        
        query = Firmware.query
        if active_only:
            query = query.filter_by(is_active=True)
        
        firmwares = query.order_by(Firmware.created_at.desc()).all()
        
        return jsonify({
            'firmware': [f.to_dict() for f in firmwares],
            'total': len(firmwares)
        })
    except Exception as e:
        logger.error(f"Error listing firmware: {e}", exc_info=True)
        return jsonify({'error': 'Internal server error'}), 500


@app.teardown_appcontext
def shutdown_session(exception=None):
    """요청 종료 시 세션 정리"""
    db.session.remove()


if __name__ == '__main__':
    # 설정 검증
    Config.validate()
    
    # 데이터베이스 초기화
    init_db()
    
    # MQTT 핸들러 초기화
    init_mqtt()
    
    # 서버 시작
    logger.info(f"Starting OTA Server on {Config.HOST}:{Config.PORT}")
    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG
    )
