"""
OTA Server - Configuration
환경 변수 및 설정 관리
"""
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


class Config:
    """서버 설정 클래스"""
    
    # Flask 설정
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # 데이터베이스 설정
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'ota_db')
    DB_USER = os.getenv('DB_USER', 'ota_user')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'ota_password')
    
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG
    
    # 서버 설정
    HOST = os.getenv('HOST', '0.0.0.0')
    PORT = int(os.getenv('PORT', '8080'))
    
    # 펌웨어 저장 경로
    FIRMWARE_DIR = os.getenv('FIRMWARE_DIR', './firmware_files')
    
    # MQTT 설정
    MQTT_BROKER_HOST = os.getenv('MQTT_BROKER_HOST', 'localhost')
    MQTT_BROKER_PORT = int(os.getenv('MQTT_BROKER_PORT', '1883'))
    MQTT_CLIENT_ID = os.getenv('MQTT_CLIENT_ID', 'ota-server')
    MQTT_USERNAME = os.getenv('MQTT_USERNAME', '')
    MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', '')
    MQTT_KEEPALIVE = int(os.getenv('MQTT_KEEPALIVE', '60'))
    MQTT_QOS = int(os.getenv('MQTT_QOS', 2))
    
    # MQTT 토픽 템플릿
    MQTT_TOPIC_CMD = 'ota/{vehicle_id}/cmd'
    MQTT_TOPIC_STATUS = 'ota/{vehicle_id}/status'
    MQTT_TOPIC_PROGRESS = 'ota/{vehicle_id}/progress'
    
    # 로깅 설정
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    @classmethod
    def validate(cls):
        """설정 검증"""
        if not os.path.exists(cls.FIRMWARE_DIR):
            os.makedirs(cls.FIRMWARE_DIR)
            print(f"Created firmware directory: {cls.FIRMWARE_DIR}")
        
        return True