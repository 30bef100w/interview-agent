"""岗位分类服务单测。"""
from app.services.job_roles import (
    all_categories,
    infer_roles,
    load_companies,
    resolve_target_roles,
    role_name,
)


def test_job_catalog_loads():
    cats = all_categories()
    assert "后端开发" in cats
    assert "java_backend" in cats["后端开发"]
    assert role_name("java_backend") == "Java 后端"
    assert any(c["id"] == "tencent" for c in load_companies()["companies"])


def test_infer_roles_from_profile():
    profile = {
        "skills": ["Spring Boot", "MyBatis", "Redis", "微服务"],
        "projects": [{"name": "交易平台", "stack": ["Spring Cloud", "JVM"]}],
    }
    roles = infer_roles(profile)
    assert "java_backend" in roles
    assert roles[0] == "java_backend"


def test_php_backend_in_catalog_and_infer():
    cats = all_categories()
    assert "php_backend" in cats["后端开发"]
    assert role_name("php_backend") == "PHP 后端"
    roles = infer_roles({"skills": ["Laravel", "Swoole", "PHP 后端"]})
    assert "php_backend" in roles


def test_resolve_target_roles_by_name_and_category():
    assert resolve_target_roles("搜广推") == ["recsys"]
    assert resolve_target_roles("Java 后端") == ["java_backend"]
    backend = resolve_target_roles("后端开发")
    assert "java_backend" in backend
    assert "python_backend" in backend
    assert resolve_target_roles("recsys") == ["recsys"]
    assert resolve_target_roles("") == []


def test_resolve_company_id_and_display_name():
    from app.services.job_roles import company_display_name, resolve_company_id

    assert resolve_company_id("腾讯") == "tencent"
    assert resolve_company_id("tencent") == "tencent"
    assert resolve_company_id("字节跳动") == "bytedance"
    assert resolve_company_id("字节") == "bytedance"
    assert company_display_name("tencent") == "腾讯"
    assert company_display_name("腾讯") == "腾讯"
    assert resolve_company_id("") is None
