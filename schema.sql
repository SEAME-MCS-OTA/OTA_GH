-- OTA 시스템 데이터베이스 스키마
-- PostgreSQL 14+

-------------------------------------------------------------
-- 차량 정보 테이블
CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    vehicle_id VARCHAR(100) UNIQUE NOT NULL,
    current_version VARCHAR(50),
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'idle',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX idx_vehicles_vehicle_id ON vehicles(vehicle_id);
CREATE INDEX idx_vehicles_status ON vehicles(status);
CREATE INDEX idx_vehicles_last_seen ON vehicles(last_seen);
-------------------------------------------------------------


-------------------------------------------------------------
-- 펌웨어 정보 테이블
CREATE TABLE IF NOT EXISTS firmware (
    id SERIAL PRIMARY KEY,
    version VARCHAR(50) UNIQUE NOT NULL,
    filename VARCHAR(255) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    file_size BIGINT NOT NULL,
    file_path VARCHAR(512) NOT NULL,
    release_notes TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX idx_firmware_version ON firmware(version);
CREATE INDEX idx_firmware_is_active ON firmware(is_active);
CREATE INDEX idx_firmware_created_at ON firmware(created_at DESC);
-------------------------------------------------------------


-------------------------------------------------------------
-- 업데이트 히스토리 테이블
CREATE TABLE IF NOT EXISTS update_history (
    id SERIAL PRIMARY KEY,
    vehicle_id VARCHAR(100) NOT NULL,
    firmware_id INTEGER REFERENCES firmware(id),
    from_version VARCHAR(50),
    target_version VARCHAR(50) NOT NULL,
    update_type VARCHAR(20), -- full, delta
    status VARCHAR(50) NOT NULL, -- downloading, verifying, installing, completed, failed
    progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100),
    message TEXT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    --- “update_history 테이블에 기록되는 모든 vehicle_id는     반드시 vehicles 테이블에 이미 존재하는 vehicle_id여야 한다”
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id) ON DELETE CASCADE
);

-- 인덱스
CREATE INDEX idx_update_history_vehicle_id ON update_history(vehicle_id);
CREATE INDEX idx_update_history_status ON update_history(status);
CREATE INDEX idx_update_history_started_at ON update_history(started_at DESC);
CREATE INDEX idx_update_history_vehicle_version ON update_history(vehicle_id, target_version);
-------------------------------------------------------------



-------------------------------------------------------------
-- 자동 updated_at 업데이트 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 트리거 생성
CREATE TRIGGER update_vehicles_updated_at BEFORE UPDATE ON vehicles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_firmware_updated_at BEFORE UPDATE ON firmware
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_update_history_updated_at BEFORE UPDATE ON update_history
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-------------------------------------------------------------

-- 샘플 데이터 (테스트용)
-- 주석 해제하여 사용
-- INSERT INTO firmware (version, filename, sha256, file_size, release_notes, is_active)
-- VALUES 
--     ('1.0.0', 'app_1.0.0.tar.gz', 'dummy_sha256_1.0.0', 1024, 'Initial release', false),
--     ('1.0.1', 'app_1.0.1.tar.gz', 'dummy_sha256_1.0.1', 2048, 'Bug fixes and improvements', true);
