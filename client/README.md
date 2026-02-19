# OTA Client

OTA 업데이트 클라이언트 (간결 버전)

## 🚀 빠른 시작

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 환경 설정
cp .env.example .env
# .env 파일 수정

# 3. 실행
python client.py
```

## ⚙️ 주요 설정

### 서버
```bash
OTA_SERVER_URL=http://localhost:8080  # 서버 주소
```

### 동작 모드
```bash
OTA_MODE=mqtt      # mqtt: 서버 푸시 / polling: 주기적 확인
```

### 설치 모드
```bash
INSTALL_MODE=file_copy   # file_copy: 파일 복사 / systemd: 서비스 재시작
```

## 📖 사용 예시

### MQTT 모드
```bash
export OTA_MODE=mqtt
python client.py
```

서버에서 업데이트 트리거:
```bash
curl -X POST http://localhost:8080/api/v1/admin/trigger-update \
  -H "Content-Type: application/json" \
  -d '{"vehicle_id": "vehicle_001"}'
```

### Polling 모드
```bash
export OTA_MODE=polling
export UPDATE_CHECK_INTERVAL=30
python client.py
```

## 📂 파일 구조

```
client/
├── client.py           # 메인 클라이언트 (350줄)
├── config.py           # 설정 관리
├── requirements.txt    # 의존성
├── .env.example        # 환경 변수 예시
└── README.md           # 이 파일
```

## 🔧 코드 구조

```python
OTAClient
├── 버전 관리
│   ├── _load_version()
│   └── _save_version()
│
├── 업데이트
│   ├── check_for_updates()
│   ├── download_firmware()
│   ├── verify_firmware()
│   └── perform_update()
│
├── 설치
│   ├── install_firmware()
│   ├── _install_file_copy()
│   └── _install_systemd()
│
├── 상태 리포트
│   ├── _report_status()
│   └── _report_progress()
│
├── MQTT
│   ├── _init_mqtt()
│   ├── _connect_mqtt()
│   ├── _on_mqtt_connect()
│   └── _on_mqtt_message()
│
└── 실행
    ├── run_polling_mode()
    ├── run_mqtt_mode()
    └── run()
```

## 📊 상태 흐름

```
idle → downloading → verifying → installing → completed
                                            ↓
                                         failed
```

## 🔍 로그 레벨

```bash
LOG_LEVEL=DEBUG   # 상세 로그
LOG_LEVEL=INFO    # 기본 (권장)
LOG_LEVEL=WARNING # 경고만
LOG_LEVEL=ERROR   # 에러만
```

## 💡 팁

### 테스트용 펌웨어 생성
```bash
# 간단한 앱 디렉토리 생성
mkdir -p test_app
echo "v1.0.1" > test_app/version.txt
echo "print('Hello from v1.0.1')" > test_app/app.py

# tar.gz로 압축
tar -czf app_1.0.1.tar.gz -C test_app .
```

### 서버에 펌웨어 업로드
```bash
curl -X POST http://localhost:8080/api/v1/admin/firmware \
  -F "file=@app_1.0.1.tar.gz" \
  -F "version=1.0.1" \
  -F "release_notes=Test version"
```

## 🐛 트러블슈팅

### MQTT 연결 실패
```bash
# 브로커 확인
telnet localhost 1883

# 로그 확인
export LOG_LEVEL=DEBUG
python client.py
```

### SHA256 검증 실패
```bash
# 수동 검증
sha256sum /tmp/ota_downloads/app_1.0.1.tar.gz
```

### systemd 재시작 실패
```bash
# 서비스 확인
systemctl status myapp.service

# 권한 설정 (sudo 없이 재시작)
# /etc/sudoers.d/ota-client
myuser ALL=(ALL) NOPASSWD: /bin/systemctl restart myapp.service
```