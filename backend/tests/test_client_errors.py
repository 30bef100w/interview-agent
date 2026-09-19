from app.services.client_errors import public_error_message


def test_public_error_keeps_known_user_messages():
    assert public_error_message("会话不存在") == "会话不存在"
    assert public_error_message("面试已结束") == "面试已结束"
    assert public_error_message("未知消息类型: foo") == "未知消息类型: foo"


def test_public_error_hides_python_nameerror():
    err = NameError("name 'get_redis' is not defined")
    assert public_error_message(err) == "面试官暂时没跟上，请再试一次"
    assert "get_redis" not in public_error_message(str(err))


def test_public_error_hides_long_or_path_like_text():
    assert public_error_message("file \"/app/foo.py\", line 12") == "面试官暂时没跟上，请再试一次"
    assert public_error_message("a" * 200) == "面试官暂时没跟上，请再试一次"
