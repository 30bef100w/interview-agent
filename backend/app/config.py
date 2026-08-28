from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "face-agent"
    app_env: str = "development"  # development | production
    debug: bool = True
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    database_url: str = "sqlite:///./data/face_agent.db"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    whisper_model: str = "small"  # tiny | base | small（越大越准越慢；上传兜底用）
    admin_usernames: str = ""  # 逗号分隔，登录时同步 is_admin=1
    default_platform_quota: int = 3  # 新用户平台 Key 试用面试次数
    # 逗号分隔；生产经 Nginx 同源时可留空
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    public_origin: str = ""  # 可选：单个对外域名，自动并入 CORS

    # 错标审核队列（可选 RocketMQ）
    rocketmq_namesrv: str = ""
    rocketmq_tag_mismatch_topic: str = ""
    rocketmq_producer_group: str = "face-agent-tag-mismatch"

    # Redis（会话 checkpoint；未配置则回落文件）
    redis_url: str = ""

    # 飞书运维告警（群机器人 Webhook）
    feishu_webhook_url: str = ""
    feishu_webhook_secret: str = ""  # 自定义机器人「签名校验」secret；未开启可留空
    feishu_tag_mismatch_batch: int = 10  # 错标 pending 每满 N 条发一批报告

    # 飞书运维告警（冷却秒数、流量 RPM 阈值；0=关闭流量告警）
    alert_cooldown_seconds: int = 600
    alert_rpm_threshold: int = 180

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("app_env")
    @classmethod
    def _norm_env(cls, v: str) -> str:
        return (v or "development").strip().lower()

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        pub = self.public_origin.strip()
        if pub and pub not in origins:
            origins.append(pub)
        return origins

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


settings = Settings()
