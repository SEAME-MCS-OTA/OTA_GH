#!/bin/bash
# OTA 시스템 빠른 시작 스크립트

set -e

# 대시보드 설정
DASHBOARD_DIR="./dashboard"
DASHBOARD_PID_FILE="${DASHBOARD_DIR}/.dashboard.pid"
DASHBOARD_LOG_FILE="${DASHBOARD_DIR}/dashboard.log"
DASHBOARD_PORT=3000

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
cat << "EOF"
  ___  _____  _    
 / _ \|_   _|/ \   
| | | | | | / _ \  
| |_| | | |/ ___ \ 
 \___/  |_/_/   \_\

OTA System Quick Start
EOF
echo -e "${NC}"

# 1. 환경 확인
echo -e "${YELLOW}[1/7] 환경 확인${NC}"

# Docker 확인
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker가 설치되어 있지 않습니다${NC}"
    echo "Docker 설치: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✓ Docker 설치됨${NC}"

# Docker Compose 확인
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}✗ Docker Compose가 설치되어 있지 않습니다${NC}"
    echo "Docker Compose 설치: https://docs.docker.com/compose/install/"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose 설치됨${NC}"
echo ""

# 2. 환경 변수 설정
echo -e "${YELLOW}[2/7] 환경 변수 설정${NC}"

if [ ! -f .env ]; then
    cat > .env << 'EOF'
# OTA System Environment Variables

# Database
DB_NAME=ota_db
DB_USER=ota_user
DB_PASSWORD=ota_password_change_me
DB_PORT=5432

# Server
SERVER_PORT=8080
SECRET_KEY=your-secret-key-change-me
DEBUG=False
LOG_LEVEL=INFO

# MQTT
MQTT_BROKER_PORT=1883
EOF
    echo -e "${GREEN}✓ .env 파일 생성됨${NC}"
else
    echo -e "${BLUE}i .env 파일이 이미 존재합니다${NC}"
fi
echo ""

# 3. 디렉토리 생성
echo -e "${YELLOW}[3/7] 디렉토리 생성${NC}"
mkdir -p firmware_files
echo -e "${GREEN}✓ firmware_files/ 디렉토리 생성${NC}"
echo ""

# 4. Docker Compose 실행
echo -e "${YELLOW}[4/7] Docker 컨테이너 시작${NC}"
echo "이 작업은 몇 분 소요될 수 있습니다..."
echo ""

if docker compose version &> /dev/null; then
    docker compose up -d
else
    docker-compose up -d
fi

echo ""
echo -e "${GREEN}✓ 컨테이너 시작됨${NC}"
echo ""

# 5. 서비스 준비 대기
echo -e "${YELLOW}[5/7] 서비스 준비 대기${NC}"
echo "서버가 준비될 때까지 대기 중..."

MAX_WAIT=60
WAIT_TIME=0
while [ $WAIT_TIME -lt $MAX_WAIT ]; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 서버 준비 완료${NC}"
        break
    fi
    sleep 2
    WAIT_TIME=$((WAIT_TIME + 2))
    echo -n "."
done

if [ $WAIT_TIME -ge $MAX_WAIT ]; then
    echo ""
    echo -e "${YELLOW}! 서버 준비에 시간이 걸리고 있습니다${NC}"
    echo "로그 확인: docker logs ota-server"
fi
echo ""

# 6. 상태 확인
echo -e "${YELLOW}[6/7] 시스템 상태 확인${NC}"

if docker compose version &> /dev/null; then
    docker compose ps
else
    docker-compose ps
fi
echo ""

# 헬스체크
if curl -s http://localhost:8080/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://localhost:8080/health)
    echo -e "${GREEN}✓ OTA 서버: 정상${NC}"
    echo "${HEALTH}" | python3 -m json.tool 2>/dev/null || echo "${HEALTH}"
else
    echo -e "${RED}✗ OTA 서버: 연결 실패${NC}"
fi
echo ""

# 7. 대시보드 실행
echo -e "${YELLOW}[7/7] 대시보드 시작${NC}"

if [ ! -d "${DASHBOARD_DIR}" ]; then
    echo -e "${YELLOW}! dashboard 디렉토리가 없어 건너뜁니다${NC}"
else
    if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
        echo -e "${YELLOW}! Node.js/npm이 없어 대시보드 자동 실행을 건너뜁니다${NC}"
        echo "  수동 실행: cd dashboard && npm install && npm run dev"
    elif [ ! -f "${DASHBOARD_DIR}/package.json" ]; then
        echo -e "${YELLOW}! dashboard/package.json이 없어 대시보드 실행을 건너뜁니다${NC}"
    else
        DASHBOARD_READY=true

        # 의존성 설치 (필요 시)
        if [ ! -d "${DASHBOARD_DIR}/node_modules" ]; then
            echo "대시보드 의존성 설치 중..."
            if ! (cd "${DASHBOARD_DIR}" && npm install); then
                echo -e "${YELLOW}! npm install 실패로 대시보드 실행을 건너뜁니다${NC}"
                DASHBOARD_READY=false
            fi
        fi

        # 기존 PID 정리/확인
        if [ -f "${DASHBOARD_PID_FILE}" ]; then
            DASHBOARD_PID=$(cat "${DASHBOARD_PID_FILE}" 2>/dev/null || true)
            if [ -n "${DASHBOARD_PID}" ] && kill -0 "${DASHBOARD_PID}" 2>/dev/null; then
                echo -e "${BLUE}i 대시보드가 이미 실행 중입니다 (PID: ${DASHBOARD_PID})${NC}"
                DASHBOARD_READY=false
            else
                rm -f "${DASHBOARD_PID_FILE}"
            fi
        fi

        # 대시보드 시작
        if [ "${DASHBOARD_READY}" = true ]; then
            echo "대시보드 시작 중..."
            (
                cd "${DASHBOARD_DIR}"
                nohup npm run dev -- --host 0.0.0.0 --port "${DASHBOARD_PORT}" \
                    > "$(basename "${DASHBOARD_LOG_FILE}")" 2>&1 &
                echo $! > "$(basename "${DASHBOARD_PID_FILE}")"
            )

            sleep 2

            NEW_DASHBOARD_PID=$(cat "${DASHBOARD_PID_FILE}" 2>/dev/null || true)
            if [ -n "${NEW_DASHBOARD_PID}" ] && kill -0 "${NEW_DASHBOARD_PID}" 2>/dev/null; then
                echo -e "${GREEN}✓ 대시보드 실행됨 (PID: ${NEW_DASHBOARD_PID})${NC}"
            else
                echo -e "${YELLOW}! 대시보드 시작 확인 실패 (로그 확인: ${DASHBOARD_LOG_FILE})${NC}"
            fi
        fi
    fi
fi
echo ""

# 완료 메시지
echo -e "${GREEN}"
cat << "EOF"
========================================
  OTA 시스템 시작 완료!
========================================
EOF
echo -e "${NC}"

echo "📡 서버 URL: http://localhost:8080"
echo "🖥️  Dashboard: http://localhost:${DASHBOARD_PORT}"
echo "🗄️  PostgreSQL: localhost:5432"
echo "📨 MQTT 브로커: localhost:1883"
echo ""

echo -e "${BLUE}다음 단계:${NC}"
echo ""
echo "1️⃣  대시보드 로그 확인:"
echo "   tail -f ${DASHBOARD_LOG_FILE}"
echo ""
echo "2️⃣  펌웨어 생성:"
echo "   chmod +x scripts/*.sh"
echo "   ./scripts/create_firmware.sh 1.0.1"
echo ""
echo "3️⃣  상태 확인:"
echo "   ./scripts/check_status.sh"
echo ""
echo "4️⃣  클라이언트 실행:"
echo "   cd client"
echo "   pip install -r requirements.txt"
echo "   cp .env.example .env"
echo "   python client.py"
echo ""
echo "5️⃣  서버 로그 확인:"
echo "   docker logs -f ota-server"
echo ""
echo "6️⃣  중지:"
if docker compose version &> /dev/null; then
    echo "   docker compose down"
else
    echo "   docker-compose down"
fi
echo "   [ -f ${DASHBOARD_PID_FILE} ] && kill \$(cat ${DASHBOARD_PID_FILE})"
echo ""

echo -e "${YELLOW}자세한 사용법은 RUNNING_GUIDE.md를 참고하세요${NC}"
echo ""
