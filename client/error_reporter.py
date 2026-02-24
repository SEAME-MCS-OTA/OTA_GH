"""
OTA Error Reporter
OTA 업데이트 중 발생한 오류를 구조화된 로그로 수집하고 서버에 전송하는 모듈

[데이터 흐름]
OTAClient (client.py)
  └─ classify_exception()   : 발생한 예외 → ErrorCode 자동 분류
  └─ build_error_report()   : 오류 로그 딕셔너리 생성
  └─ send_error_report()    : 기본 서버 POST /api/v1/error-report
       └─ OTA_ERROR_REPORT_URL 설정 시 해당 URL로 직접 전송 (예: OTA_VLM /ingest)
  └─ report_ota_success()   : 성공 이벤트(error.code=NONE) 전송
       └─ (향후) VLM 분석 → 메일 발송 파이프라인으로 확장 예정

[현재 환경에서 감지 가능한 오류]
  DOWNLOAD 단계
    NET_TIMEOUT        : requests.exceptions.Timeout
    DNS_FAIL           : ConnectionError + "Name or service not known" / "Errno -2"
    HTTP_5XX           : response.status_code 500–599
    POLICY_REJECT      : response.status_code 403
    DISK_FULL          : OSError "No space left" / statvfs 체크

  VERIFY 단계
    HASH_MISMATCH      : SHA256 불일치 (verify_firmware)
    DISK_FULL          : 파일 읽기 중 OSError

  INSTALL 단계
    DISK_FULL          : tarfile 압축 해제 중 OSError
    SYSTEMD_UNIT_FAILED: systemctl restart returncode != 0
    SERVICE_CRASH      : systemctl is-active → inactive/failed

  공통
    UNKNOWN            : 위 분류 외 모든 Exception fallback
"""

import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# standalone 실행 시에도 client/.env 설정을 사용
load_dotenv()


# ──────────────────────────────────────────────
# 상수 정의
# ──────────────────────────────────────────────

class OTAPhase:
    """OTA 업데이트 단계"""
    DOWNLOAD = "DOWNLOAD"
    VERIFY   = "VERIFY"
    INSTALL  = "INSTALL"
    ROLLBACK = "ROLLBACK"


class OTAEvent:
    """OTA 이벤트 타입"""
    OK      = "OK"
    FAIL    = "FAIL"
    TIMEOUT = "TIMEOUT"
    ABORT   = "ABORT"


class ErrorCode:
    """
    OTA 오류 분류 코드
    """
    NONE                 = "NONE"
    NET_TIMEOUT          = "NET_TIMEOUT"
    DNS_FAIL             = "DNS_FAIL"
    HTTP_5XX             = "HTTP_5XX"
    HASH_MISMATCH        = "HASH_MISMATCH"
    DISK_FULL            = "DISK_FULL"
    SYSTEMD_UNIT_FAILED  = "SYSTEMD_UNIT_FAILED"
    SERVICE_CRASH        = "SERVICE_CRASH"
    POLICY_REJECT        = "POLICY_REJECT"
    UNKNOWN              = "UNKNOWN"


# 재시도 가능한 에러 코드 목록
RETRYABLE_ERRORS = {
    ErrorCode.NET_TIMEOUT,
    ErrorCode.DNS_FAIL,
    ErrorCode.HTTP_5XX,
}

# 디스크 경고 임계값 (%)
DISK_WARN_THRESHOLD = 90

# 환경변수로 에러 리포트 전송 대상을 직접 지정 가능
# 예) OTA_ERROR_REPORT_URL=http://localhost:4000/ingest
ERROR_REPORT_URL_ENV = "OTA_ERROR_REPORT_URL"


# ──────────────────────────────────────────────
# ErrorCode 자동 분류
# ──────────────────────────────────────────────

def classify_exception(exc: Exception, http_status: Optional[int] = None) -> str:
    """
    발생한 예외와 HTTP 상태 코드를 받아 ErrorCode 문자열을 반환합니다.
    client.py의 except 블록에서 error_code를 직접 판단하지 않아도 됩니다.

    Parameters
    ----------
    exc         : 발생한 예외 객체
    http_status : HTTP 응답 코드 (있을 경우 우선 판단)

    Returns
    -------
    str : ErrorCode.*

    Examples
    --------
    # download_firmware()
    except requests.exceptions.Timeout as e:
        code = classify_exception(e)                  # → "NET_TIMEOUT"

    except requests.exceptions.ConnectionError as e:
        code = classify_exception(e)                  # → "DNS_FAIL" or "UNKNOWN"

    except requests.exceptions.HTTPError as e:
        code = classify_exception(e, response.status_code)  # → "HTTP_5XX" / "POLICY_REJECT"

    # verify_firmware()
    except ValueError as e:          # sha256 불일치를 ValueError로 raise
        code = classify_exception(e)  # → "HASH_MISMATCH"

    # install / systemd
    except OSError as e:
        code = classify_exception(e)  # → "DISK_FULL" or "UNKNOWN"
    """
    # 1) HTTP 상태 코드 기반 우선 분류
    if http_status is not None:
        if 500 <= http_status <= 599:
            return ErrorCode.HTTP_5XX
        if http_status == 403:
            return ErrorCode.POLICY_REJECT

    exc_msg = str(exc).lower()

    # 2) requests 예외 분류
    if isinstance(exc, requests.exceptions.Timeout):    # isinstace(A, B) : A가 B의 서브클래스이거나 같은 클래스인지 확인
        return ErrorCode.NET_TIMEOUT

    if isinstance(exc, requests.exceptions.ConnectionError):
        # DNS 해석 실패 키워드
        dns_keywords = (
            "name or service not known",
            "nodename nor servname",
            "errno -2",
            "getaddrinfo failed",
            "temporary failure in name resolution",
        )
        if any(kw in exc_msg for kw in dns_keywords):
            return ErrorCode.DNS_FAIL
        return ErrorCode.NET_TIMEOUT  # DNS 외 연결 실패는 일반 타임아웃으로 분류

    if isinstance(exc, requests.exceptions.HTTPError):
        # http_status가 전달되지 않았을 때 메시지에서 파싱 시도
        if "403" in exc_msg:
            return ErrorCode.POLICY_REJECT
        if any(c in exc_msg for c in ("500", "502", "503", "504")):
            return ErrorCode.HTTP_5XX
        return ErrorCode.UNKNOWN

    # 3) OS/IO 예외 분류
    if isinstance(exc, OSError):
        disk_keywords = (
            "no space left",
            "enospc",
            "disk full",
            "not enough space",
        )
        if any(kw in exc_msg for kw in disk_keywords):
            return ErrorCode.DISK_FULL
        return ErrorCode.UNKNOWN

    # 4) SHA256 불일치 (verify_firmware에서 ValueError로 raise)
    if isinstance(exc, ValueError):
        hash_keywords = ("sha256", "hash", "checksum", "mismatch", "digest")
        if any(kw in exc_msg for kw in hash_keywords):
            return ErrorCode.HASH_MISMATCH
        return ErrorCode.UNKNOWN

    return ErrorCode.UNKNOWN


def classify_systemd_error(returncode: int, stderr: str, is_active: bool) -> str:
    """
    systemd 관련 오류를 분류합니다. (_install_systemd 전용)

    Parameters
    ----------
    returncode : systemctl restart의 returncode
    stderr     : systemctl restart의 stderr 출력
    is_active  : systemctl is-active 결과 (True=active)

    Returns
    -------
    str : ErrorCode.SYSTEMD_UNIT_FAILED | ErrorCode.SERVICE_CRASH | ErrorCode.UNKNOWN
    """
    if returncode != 0:
        return ErrorCode.SYSTEMD_UNIT_FAILED
    if not is_active:
        return ErrorCode.SERVICE_CRASH
    return ErrorCode.UNKNOWN


# ──────────────────────────────────────────────
# 컨텍스트 수집 헬퍼
# ──────────────────────────────────────────────

def _get_time_bucket(hour: int) -> str:     # 시간대 버킷 (MORNING, AFTERNOON, EVENING, NIGHT)
    if 6 <= hour < 12:
        return "MORNING"
    elif 12 <= hour < 18:
        return "AFTERNOON"
    elif 18 <= hour < 22:
        return "EVENING"
    else:
        return "NIGHT"


def _collect_time_context() -> dict:
    now_local = datetime.now()
    return {
        "local": now_local.isoformat(timespec="seconds"),
        "day_of_week": now_local.strftime("%a"),
        "time_bucket": _get_time_bucket(now_local.hour),
    }


def _collect_filesystem_context(firmware_dir: str = "/tmp") -> list:
    """
    디스크 사용량 수집 및 임계값 경고
    - 현재 환경에서 실제 측정 가능한 유일한 HW 지표
    """
    logs = []
    try:
        stat = os.statvfs(firmware_dir)
        total    = stat.f_frsize * stat.f_blocks
        free     = stat.f_frsize * stat.f_bfree
        used_pct = round((1 - free / total) * 100, 1) if total > 0 else 0
        free_mb  = round(free / (1024 ** 2), 1)

        logs.append(f"disk_used={used_pct}% free={free_mb}MB path={firmware_dir}")

        if used_pct >= DISK_WARN_THRESHOLD:
            logs.append(f"WARNING: disk usage critical ({used_pct}% >= {DISK_WARN_THRESHOLD}%)")

    except Exception as e:
        logs.append(f"filesystem_check_error: {e}")

    return logs


# ──────────────────────────────────────────────
# 핵심 함수
# ──────────────────────────────────────────────

def build_error_report(
    # --- 필수: OTA 식별 정보 ---
    device_id: str,
    current_version: str,
    target_version: str,
    phase: str,
    error_code: str,
    error_message: str,

    # --- 선택: OTA 메타 ---
    event: str = OTAEvent.FAIL,
    ota_id: Optional[str] = None,

    # --- 선택: 지역/전원 (RPi 연동 전까지 기본값 사용) ---
    country: Optional[str] = None,
    city: Optional[str] = None,
    tz_name: Optional[str] = None,
    power_source: Optional[str] = None,
    battery_pct: Optional[int] = None,

    # --- 선택: 네트워크 (측정값 있을 때만 포함) ---
    rssi_dbm: Optional[int] = None,
    latency_ms: Optional[int] = None,

    # --- 증거 로그 ---
    ota_log: Optional[list] = None,
    journal_log: Optional[list] = None,
    firmware_dir: str = "/tmp",

    # --- 선택: VLM/분석 메타 (OTA_VLM 대시보드 호환) ---
    vlm_root_cause: Optional[str] = None,
    vlm_confidence: Optional[float] = None,
    vlm_supporting_evidence: Optional[list] = None,
    analysis_tags: Optional[list] = None,
) -> dict:
    """
    OTA 오류 보고서 딕셔너리를 생성합니다.

    RPi/실제 HW 없는 현재 환경에서 측정 불가한 필드
    (battery_pct, rssi_dbm, latency_ms, country, city, tz_name)는
    전달하지 않으면 보고서에서 자동으로 제외됩니다.

    Returns
    -------
    dict : 서버 전송용 구조화된 오류 보고서
    """
    now    = datetime.now().astimezone()
    ts     = now.isoformat(timespec="seconds")
    ota_id = ota_id or f"ota-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"

    retryable = error_code in RETRYABLE_ERRORS

    # region: 값이 있는 필드만 포함
    region_ctx: dict = {}
    if country:  region_ctx["country"]  = country
    if city:     region_ctx["city"]     = city
    if tz_name:  region_ctx["timezone"] = tz_name

    # power: 현재 환경에서는 source / battery 모두 생략 가능
    power_ctx: dict = {}
    if power_source:
        power_ctx["source"] = power_source
    if battery_pct is not None:
        # OTA_VLM ingest 호환: context.power.battery_pct 를 직접 읽음
        power_ctx["battery_pct"] = battery_pct
        power_ctx["battery"] = {"pct": battery_pct}

    # network: 측정값이 있을 때만 포함
    network_ctx: dict = {}
    if rssi_dbm  is not None: network_ctx["rssi_dbm"]   = rssi_dbm
    if latency_ms is not None: network_ctx["latency_ms"] = latency_ms

    # context 조립 (비어있는 블록은 제외)
    context: dict = {"time": _collect_time_context()}
    if region_ctx:  context["region"]  = region_ctx
    if power_ctx:   context["power"]   = power_ctx
    if network_ctx: context["network"] = network_ctx

    report = {
        "ts": ts,
        "device": {
            "device_id": device_id,
        },
        "ota": {
            "ota_id":          ota_id,
            "current_version": current_version,
            "target_version":  target_version,
            "phase":           phase,
            "event":           event,
        },
        "context": context,
        "error": {
            "code":      error_code,
            "message":   error_message,
            "retryable": retryable,
        },
        # OTA_VLM backend는 root-cause 집계 시 vlm.root_cause를 사용하므로,
        # 값이 없으면 error_code를 기본 root cause로 채운다.
        "vlm": {
            "root_cause": vlm_root_cause or error_code or ErrorCode.UNKNOWN,
            "confidence": float(vlm_confidence) if vlm_confidence is not None else 1.0,
            "supporting_evidence": vlm_supporting_evidence or ota_log or [],
        },
        "analysis": {
            "tags": analysis_tags or [phase, error_code],
        },
        "evidence": {
            "ota_log":     ota_log     or [],
            "journal_log": journal_log or [],
            "filesystem":  _collect_filesystem_context(firmware_dir),
        },
    }

    return report


def _resolve_report_endpoint(
    server_url: str,
    endpoint_override: Optional[str] = None,
    default_path: str = "/api/v1/error-report",
) -> str:
    """
    에러 리포트 전송 endpoint를 결정합니다.

    우선순위
    1) endpoint_override 인자
    2) 환경변수 OTA_ERROR_REPORT_URL
    3) server_url 이 경로까지 포함한 완전한 URL이면 그대로 사용
    4) 기본값: {server_url}/api/v1/error-report
    """
    # 1) 인자 override
    if endpoint_override:
        return endpoint_override.rstrip("/")

    # 2) 환경변수 override
    env_endpoint = os.getenv(ERROR_REPORT_URL_ENV, "").strip()
    if env_endpoint:
        return env_endpoint.rstrip("/")

    base = server_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme and parsed.netloc and parsed.path not in ("", "/"):
        # 3) 이미 endpoint 포함 URL로 판단
        return base

    # 4) 기본 경로 결합
    return f"{base}{default_path}"


# ──────────────────────────────────────────────
# 전송 함수
# ──────────────────────────────────────────────

def send_error_report(
    report: dict,
    server_url: str,
    endpoint_override: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    오류 보고서를 OTA 서버에 POST로 전송합니다.
    기본 Endpoint : POST {server_url}/api/v1/error-report
    예외적으로 OTA_ERROR_REPORT_URL(또는 endpoint_override)을 지정하면 해당 URL로 전송합니다.

    전송 실패(서버 다운·타임아웃) 시 /tmp/ota_error_logs/ 에 JSON fallback 저장.
    """
    endpoint = _resolve_report_endpoint(server_url, endpoint_override=endpoint_override)
    ota_id   = report.get("ota", {}).get("ota_id", "unknown")

    try:
        response = requests.post(
            endpoint,
            json=report,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        logger.info(f"[ErrorReporter] Sent OK (ota_id={ota_id}, status={response.status_code})")
        return True

    except requests.exceptions.ConnectionError as e:
        logger.error(f"[ErrorReporter] Connection failed: {e}")
        _save_report_locally(report)
        return False

    except requests.exceptions.Timeout:
        logger.error(f"[ErrorReporter] Request timed out ({timeout}s)")
        _save_report_locally(report)
        return False

    except requests.exceptions.HTTPError as e:
        logger.error(f"[ErrorReporter] HTTP error: {e}")
        return False

    except Exception as e:
        logger.error(f"[ErrorReporter] Unexpected error: {e}")
        _save_report_locally(report)
        return False


def _save_report_locally(report: dict, log_dir: str = "/tmp/ota_error_logs"):
    """서버 전송 실패 시 로컬 JSON 저장 (fallback / 향후 VLM 오프라인 분석용)"""
    try:
        os.makedirs(log_dir, exist_ok=True)
        ota_id   = report.get("ota", {}).get("ota_id", "unknown")
        ts_safe  = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = os.path.join(log_dir, f"error_report_{ota_id}_{ts_safe}.json")

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.warning(f"[ErrorReporter] Saved locally: {filename}")

    except Exception as e:
        logger.error(f"[ErrorReporter] Local save failed: {e}")


# ──────────────────────────────────────────────
# 편의 래퍼
# ──────────────────────────────────────────────

def report_ota_error(
    device_id: str,
    current_version: str,
    target_version: str,
    phase: str,
    error_code: str,
    error_message: str,
    server_url: str,
    endpoint_override: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    build_error_report() + send_error_report() 통합 편의 함수.
    client.py의 except 블록에서 한 줄로 호출합니다.

    ── DOWNLOAD 예시 ──────────────────────────────────────────
    except requests.exceptions.Timeout as e:
        report_ota_error(
            device_id       = Config.VEHICLE_ID,
            current_version = self.current_version,
            target_version  = firmware_info['version'],
            phase           = OTAPhase.DOWNLOAD,
            error_code      = classify_exception(e),        # → NET_TIMEOUT
            error_message   = str(e),
            server_url      = Config.SERVER_URL,
            ota_log         = ["DOWNLOAD START", f"TIMEOUT: {e}"],
        )

    ── VERIFY 예시 ────────────────────────────────────────────
    if calculated != expected_sha256:
        report_ota_error(
            ...
            phase      = OTAPhase.VERIFY,
            error_code = ErrorCode.HASH_MISMATCH,
            error_message = f"expected={expected_sha256[:16]} got={calculated[:16]}",
            ...
        )

    ── INSTALL / systemd 예시 ─────────────────────────────────
    error_code = classify_systemd_error(result.returncode, result.stderr, is_active)
    report_ota_error(..., phase=OTAPhase.INSTALL, error_code=error_code, ...)
    """
    report = build_error_report(
        device_id       = device_id,
        current_version = current_version,
        target_version  = target_version,
        phase           = phase,
        error_code      = error_code,
        error_message   = error_message,
        **kwargs,
    )

    logger.error(
        f"[ErrorReporter] OTA FAIL | device={device_id} "
        f"phase={phase} code={error_code} msg={error_message}"
    )

    return send_error_report(
        report=report,
        server_url=server_url,
        endpoint_override=endpoint_override,
    )


def report_ota_success(
    device_id: str,
    current_version: str,
    target_version: str,
    phase: str,
    server_url: str,
    message: str = "OTA update completed",
    event: str = OTAEvent.OK,
    endpoint_override: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    OTA 성공 이벤트를 서버로 전송합니다.
    - 통계 집계를 위해 success 레코드는 error.code = "NONE" 으로 전송
    - OTA_VLM backend에서 is_failure=0 으로 저장됨
    """
    report = build_error_report(
        device_id=device_id,
        current_version=current_version,
        target_version=target_version,
        phase=phase,
        error_code=ErrorCode.NONE,
        error_message=message,
        event=event,
        **kwargs,
    )

    logger.info(
        f"[ErrorReporter] OTA OK | device={device_id} "
        f"phase={phase} target={target_version} msg={message}"
    )

    return send_error_report(
        report=report,
        server_url=server_url,
        endpoint_override=endpoint_override,
    )


# ──────────────────────────────────────────────
# 테스트 / 출력 예시
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s - %(message)s")

    def _env_or_default(key: str, default: str) -> str:
        value = os.getenv(key, "").strip()
        return value if value else default

    def _env_or_int(key: str, default: int) -> int:
        value = os.getenv(key, "").strip()
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    parser = argparse.ArgumentParser(description="OTA error report demo")
    parser.add_argument(
        "--send",
        action="store_true",
        help="build된 DEMO report를 endpoint로 실제 전송",
    )
    parser.add_argument(
        "--server-url",
        default=os.getenv("OTA_SERVER_URL", "http://localhost:8080"),
        help="기본 OTA 서버 URL (기본: env OTA_SERVER_URL 또는 http://localhost:8080)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="전송 endpoint override (예: http://localhost:4000/ingest)",
    )
    parser.add_argument(
        "--case",
        type=int,
        default=0,
        help="0이면 전체, 1~N이면 해당 DEMO CASE만 실행",
    )
    args = parser.parse_args()

    # DEMO 실행 시 컨텍스트가 비어 대시보드 필드가 누락되지 않도록 기본값 제공
    demo_context_defaults = {
        "country": _env_or_default("OTA_REGION_COUNTRY", "DE"),
        "city": _env_or_default("OTA_REGION_CITY", "Düsseldorf"),
        "tz_name": _env_or_default("OTA_REGION_TIMEZONE", "Europe/Berlin"),
        "power_source": _env_or_default("OTA_POWER_SOURCE", "BATTERY"),
        "battery_pct": _env_or_int("OTA_BATTERY_PCT", 85),
        "rssi_dbm": _env_or_int("OTA_NETWORK_RSSI_DBM", -55),
        "latency_ms": _env_or_int("OTA_NETWORK_LATENCY_MS", 373),
    }

    DEMO_CASES = [
        # ── CASE 1: 다운로드 중 서버 오류 ──────────────────────
        dict(
            label           = "CASE 1 — DOWNLOAD / HTTP_5XX",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.DOWNLOAD,
            error_code      = ErrorCode.HTTP_5XX,
            error_message   = "Server error: 503 Service Unavailable",
            ota_log         = ["DOWNLOAD START", "DOWNLOAD FAIL code=HTTP_5XX http=503"],
            journal_log     = ["HTTP/1.1 503 Service Unavailable"],
        ),
        # ── CASE 2: DNS 해석 실패 ──────────────────────────────
        dict(
            label           = "CASE 2 — DOWNLOAD / DNS_FAIL",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.DOWNLOAD,
            error_code      = ErrorCode.DNS_FAIL,
            error_message   = "Failed to resolve 'ota.example.com': Name or service not known",
            ota_log         = ["DOWNLOAD START", "DNS_FAIL host=ota.example.com"],
            journal_log     = ["systemd-resolved: NXDOMAIN ota.example.com"],
        ),
        # ── CASE 3: 네트워크 타임아웃 ─────────────────────────
        dict(
            label           = "CASE 3 — DOWNLOAD / NET_TIMEOUT",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.DOWNLOAD,
            error_code      = ErrorCode.NET_TIMEOUT,
            error_message   = "HTTPSConnectionPool: Read timed out (read timeout=30)",
            ota_log         = ["DOWNLOAD START", "DOWNLOAD FAIL code=NET_TIMEOUT after=30s"],
            journal_log     = [],
        ),
        # ── CASE 4: SHA256 불일치 ─────────────────────────────
        dict(
            label           = "CASE 4 — VERIFY / HASH_MISMATCH",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.VERIFY,
            error_code      = ErrorCode.HASH_MISMATCH,
            error_message   = "SHA256 mismatch: expected=a3f1bc..., got=9e72dc...",
            ota_log         = [
                "DOWNLOAD COMPLETE size=4096KB",
                "VERIFY START",
                "VERIFY FAIL code=HASH_MISMATCH",
            ],
            journal_log     = [],
        ),
        # ── CASE 5: 디스크 부족 ───────────────────────────────
        dict(
            label           = "CASE 5 — INSTALL / DISK_FULL",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.INSTALL,
            error_code      = ErrorCode.DISK_FULL,
            error_message   = "[Errno 28] No space left on device",
            ota_log         = [
                "INSTALL START",
                "EXTRACT FAIL code=DISK_FULL errno=28",
            ],
            journal_log     = ["kernel: EXT4-fs error: No space left"],
        ),
        # ── CASE 6: systemd 유닛 시작 실패 ───────────────────
        dict(
            label           = "CASE 6 — INSTALL / SYSTEMD_UNIT_FAILED",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.INSTALL,
            error_code      = ErrorCode.SYSTEMD_UNIT_FAILED,
            error_message   = "systemctl restart ota-app.service failed (rc=1)",
            ota_log         = [
                "FILE COPY OK",
                "SERVICE RESTART FAIL rc=1",
            ],
            journal_log     = [
                "ota-app.service: Main process exited, code=exited, status=1",
                "Failed to start OTA Application Service.",
            ],
        ),
        # ── CASE 7: 서비스 시작 후 크래시 ────────────────────
        dict(
            label           = "CASE 7 — INSTALL / SERVICE_CRASH",
            device_id       = "sim-device-001",
            current_version = "1.2.3",
            target_version  = "1.2.4",
            phase           = OTAPhase.INSTALL,
            error_code      = ErrorCode.SERVICE_CRASH,
            error_message   = "Service not active after restart (status=failed)",
            ota_log         = [
                "SERVICE RESTART OK",
                "SERVICE HEALTH CHECK FAIL status=failed",
            ],
            journal_log     = [
                "ota-app.service: Main process exited unexpectedly",
                "ota-app.service: Failed with result 'signal'.",
            ],
        ),
    ]

    selected_cases = DEMO_CASES
    if args.case:
        if args.case < 1 or args.case > len(DEMO_CASES):
            raise SystemExit(f"--case must be between 1 and {len(DEMO_CASES)}")
        selected_cases = [DEMO_CASES[args.case - 1]]

    for idx, item in enumerate(selected_cases, start=1):
        case = dict(item)
        label = case.pop("label")
        print(f"\n{'='*60}")
        print(f"  [{idx}] {label}")
        print('='*60)
        report = build_error_report(**{**demo_context_defaults, **case})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.send:
            ok = send_error_report(
                report=report,
                server_url=args.server_url,
                endpoint_override=args.endpoint,
            )
            print(f"\nSEND RESULT: {'OK' if ok else 'FAIL'}")
