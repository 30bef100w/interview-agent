from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "face-agent"
    debug: bool = True
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    database_url: str = "sqlite:///./data/face_agent.db"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    whisper_model: str = "small"  # tiny | base | small（越大越准越慢；上传兜底用）
    admin_usernames: str = ""  # 逗号分隔，登录时同步 is_admin=1
    default_platform_quota: int = 3  # 新用户平台 Key 试用面试次数

    # 错标审核队列（可选 RocketMQ）
    rocketmq_namesrv: str = ""
    rocketmq_tag_mismatch_topic: str = ""
    rocketmq_producer_group: str = "face-agent-tag-mismatch"

    # 允许 .env 里放脚本专用变量（如 SPLIT_*），不进 Settings 字段
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
