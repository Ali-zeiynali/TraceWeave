from traceweave.utils import canonicalize_url, extract_first_json_object, is_public_ip


def test_canonicalize_url_removes_tracking_and_fragment():
    url = "HTTPS://Example.COM:443/a//b/?utm_source=x&z=2&a=1#frag"
    assert canonicalize_url(url) == "https://example.com/a/b?a=1&z=2"


def test_public_ip_policy():
    assert is_public_ip("1.1.1.1") is True
    assert is_public_ip("127.0.0.1") is False
    assert is_public_ip("10.0.0.1") is False
    assert is_public_ip("169.254.169.254") is False


def test_extract_json_from_wrapped_text():
    value = extract_first_json_object('prefix {"objective":"x","queries":["q"]} suffix')
    assert value["objective"] == "x"
