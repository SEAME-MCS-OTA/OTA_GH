#!/bin/bash
# 펌웨어 패키지 생성 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_SOURCE_DIR="${SCRIPT_DIR}/sample_app"

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 도움말
show_help() {
    cat << EOF
펌웨어 생성 스크립트

사용법:
    $0 <version> [source_dir]

인자:
    version     - 펌웨어 버전 (예: 1.0.1)
    source_dir  - 소스 디렉토리 (기본: ${DEFAULT_SOURCE_DIR})

예시:
    $0 1.0.1
    $0 1.0.1 /path/to/app

생성물:
    firmware_files/app_<version>.tar.gz

EOF
}

# 인자 확인
if [ $# -lt 1 ]; then
    echo -e "${RED}오류: 버전을 지정해주세요${NC}"
    show_help
    exit 1
fi

VERSION=$1
SOURCE_DIR=${2:-"${DEFAULT_SOURCE_DIR}"}
OUTPUT_DIR="${PROJECT_ROOT}/firmware_files"
FIRMWARE_FILE="app_${VERSION}.tar.gz"
OUTPUT_PATH="${OUTPUT_DIR}/${FIRMWARE_FILE}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}펌웨어 생성 시작${NC}"
echo -e "${GREEN}========================================${NC}"
echo "버전: ${VERSION}"
echo "소스: ${SOURCE_DIR}"
echo "출력: ${OUTPUT_PATH}"
echo ""

# 출력 디렉토리 생성
mkdir -p "${OUTPUT_DIR}"

# 소스 디렉토리 확인
if [ ! -d "${SOURCE_DIR}" ]; then
    echo -e "${YELLOW}소스 디렉토리가 없습니다. 샘플 앱을 생성합니다...${NC}"
    
    mkdir -p "${SOURCE_DIR}"
    
    # 샘플 앱 생성
    cat > "${SOURCE_DIR}/app.py" << 'PYEOF'
#!/usr/bin/env python3
"""
Sample OTA Application
"""
import sys

VERSION = "__VERSION__"

def main():
    print(f"Sample App v{VERSION}")
    print("Hello from OTA updated application!")
    
if __name__ == '__main__':
    main()
PYEOF
    
    # 버전 정보 파일
    echo "${VERSION}" > "${SOURCE_DIR}/version.txt"
    
    # README
    cat > "${SOURCE_DIR}/README.md" << 'EOF'
# Sample OTA Application

이 애플리케이션은 OTA 업데이트 테스트용 샘플입니다.

## 실행

```bash
python app.py
```

## 버전

버전 정보는 version.txt 파일에 저장되어 있습니다.
EOF
    
    echo -e "${GREEN}✓ 샘플 앱 생성 완료${NC}"
fi

# 버전 동기화
echo "${VERSION}" > "${SOURCE_DIR}/version.txt"

if [ -f "${SOURCE_DIR}/app.py" ]; then
    if grep -q "__VERSION__" "${SOURCE_DIR}/app.py"; then
        sed -i "s/__VERSION__/${VERSION}/g" "${SOURCE_DIR}/app.py"
    elif grep -Eq '^[[:space:]]*VERSION[[:space:]]*=' "${SOURCE_DIR}/app.py"; then
        sed -Ei "s|^([[:space:]]*VERSION[[:space:]]*=[[:space:]]*)[\"'][^\"']*[\"']|\\1\"${VERSION}\"|" "${SOURCE_DIR}/app.py"
    fi
fi
echo -e "${GREEN}✓ 소스 버전 동기화 완료 (version.txt/app.py)${NC}"

# 펌웨어 압축
echo -e "${YELLOW}압축 중...${NC}"
tar -czf "${OUTPUT_PATH}" -C "${SOURCE_DIR}" .

# 파일 크기 확인
FILE_SIZE=$(stat -f%z "${OUTPUT_PATH}" 2>/dev/null || stat -c%s "${OUTPUT_PATH}" 2>/dev/null)

# SHA256 계산
echo -e "${YELLOW}SHA256 계산 중...${NC}"
SHA256=$(shasum -a 256 "${OUTPUT_PATH}" | awk '{print $1}')

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}펌웨어 생성 완료!${NC}"
echo -e "${GREEN}========================================${NC}"
echo "파일: ${OUTPUT_PATH}"
echo "크기: ${FILE_SIZE} bytes"
echo "SHA256: ${SHA256}"
echo ""

# 서버 업로드 명령어 출력
echo -e "${YELLOW}서버에 업로드하려면:${NC}"
echo ""
echo "curl -X POST http://localhost:8080/api/v1/admin/firmware \\"
echo "  -F \"file=@${OUTPUT_PATH}\" \\"
echo "  -F \"version=${VERSION}\" \\"
echo "  -F \"release_notes=Release ${VERSION}\""
echo ""

# 업로드 스크립트 생성 옵션
read -p "업로드 스크립트를 생성할까요? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    UPLOAD_SCRIPT="upload_firmware_${VERSION}.sh"
    
    cat > "${UPLOAD_SCRIPT}" << EOF
#!/bin/bash
# 펌웨어 ${VERSION} 업로드 스크립트

SERVER_URL=\${OTA_SERVER_URL:-http://localhost:8080}

echo "펌웨어 업로드 중: ${VERSION}"
echo "서버: \${SERVER_URL}"

curl -X POST "\${SERVER_URL}/api/v1/admin/firmware" \\
  -F "file=@${OUTPUT_PATH}" \\
  -F "version=${VERSION}" \\
  -F "release_notes=Release ${VERSION}"

echo ""
echo "업로드 완료"
EOF
    
    chmod +x "${UPLOAD_SCRIPT}"
    echo -e "${GREEN}✓ 업로드 스크립트 생성: ${UPLOAD_SCRIPT}${NC}"
    echo "실행: ./${UPLOAD_SCRIPT}"
fi

echo ""
echo -e "${GREEN}완료!${NC}"
