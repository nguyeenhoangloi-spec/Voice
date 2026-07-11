import json
import time
import os

cookies_json = [
{
    "domain": ".douyin.com",
    "expirationDate": 1788877428.393293,
    "hostOnly": False,
    "httpOnly": False,
    "name": "__security_mc_1_s_sdk_crypt_sdk",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "684ca6d0-490f-b637",
    "id": 1
},
{
    "domain": ".douyin.com",
    "expirationDate": 1788877815.037658,
    "hostOnly": False,
    "httpOnly": False,
    "name": "bd_ticket_guard_client_data",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "eyJiZC10aWNrZXQtZ3VhcmQtdmVyc2lvbiI6MiwiYmQtdGlja2V0LWd1YXJkLWl0ZXJhdGlvbi12ZXJzaW9uIjoxLCJiZC10aWNrZXQtZ3VhcmQtcmVlLXB1YmxpYy1rZXkiOiJCRzNLeURpLytlOHJyRkg2cmkxcWxIa0ZFSFZYSVZzRHpQcTdTNmJNUWoxcmFodG5iUlkzdHJGWUh4VjVQUm4wdk5pUFNHVFpYM1RqN2lvaGJHM1ZXSVk9IiwiYmQtdGlja2V0LWd1YXJkLXdlYi12ZXJzaW9uIjoyfQ%3D%3D",
    "id": 2
},
{
    "domain": ".douyin.com",
    "expirationDate": 1788877816.115089,
    "hostOnly": False,
    "httpOnly": False,
    "name": "bd_ticket_guard_client_data_v2",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "eyJyZWVfcHVibGljX2tleSI6IkJHM0t5RGkvK2U4cnJGSDZyaTFxbEhrRkVIVlhJVnNEelBxN1M2Yk1RajFyYWh0bmJSWTN0ckZZSHhWNVBSbjB2TmlQU0dUWlgzVGo3aW9oYkczVldJWT0iLCJyZXFfY29udGVudCI6InNlY190cyIsInJlcV9zaWduIjoid0g2ZjdOU0lYUFJoOWJxTlk3Tjk3VmdGSWtSUDMvTGJVbk9hZS93UzJobz0iLCJzZWNfdHMiOiIjVzhNUGVFTWh3VnBQeDMraUdyZTN6MDVraVd6M09aYjhmeGdERHkwSUN6QStyZW1DMjZOV2pRc09YakhFIn0%3D",
    "id": 3
},
{
    "domain": ".douyin.com",
    "expirationDate": 1788877815.037872,
    "hostOnly": False,
    "httpOnly": False,
    "name": "bd_ticket_guard_client_web_domain",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "2",
    "id": 4
},
{
    "domain": ".douyin.com",
    "hostOnly": False,
    "httpOnly": False,
    "name": "biz_trace_id",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "f4563a21",
    "id": 5
},
{
    "domain": ".douyin.com",
    "expirationDate": 1784298383.733516,
    "hostOnly": False,
    "httpOnly": False,
    "name": "download_guide",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "%221%2F20260710%2F0%22",
    "id": 6
},
{
    "domain": ".douyin.com",
    "expirationDate": 1818254881.769411,
    "hostOnly": False,
    "httpOnly": False,
    "name": "enter_pc_once",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "1",
    "id": 7
},
{
    "domain": ".douyin.com",
    "expirationDate": 1818254884.54715,
    "hostOnly": False,
    "httpOnly": False,
    "name": "hevc_supported",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "true",
    "id": 8
},
{
    "domain": ".douyin.com",
    "expirationDate": 1784299687.03131,
    "hostOnly": False,
    "httpOnly": False,
    "name": "home_can_add_dy_2_desktop",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "%221%22",
    "id": 9
},
{
    "domain": ".douyin.com",
    "hostOnly": False,
    "httpOnly": False,
    "name": "is_support_rtm_web_ts",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "1",
    "id": 10
},
{
    "domain": ".douyin.com",
    "expirationDate": 1784299684.627621,
    "hostOnly": False,
    "httpOnly": False,
    "name": "IsDouyinActive",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "true",
    "id": 11
},
{
    "domain": ".douyin.com",
    "expirationDate": 1815229420.625095,
    "hostOnly": False,
    "httpOnly": True,
    "name": "odin_tt",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "0c55b011526e0247d2ce0716892640e03ec253e99a265267d01062820060a6886422548b979aefd2bc05cc5553d9fe79decddd4bd2c58662b305e855b2585bd895e43f4ef6757cb9b5fc8533d47dffbc",
    "id": 12
},
{
    "domain": ".douyin.com",
    "expirationDate": 1788877426.994971,
    "hostOnly": False,
    "httpOnly": False,
    "name": "passport_csrf_token",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "f124f72879ab0f16ed6eb57a56f320e0",
    "id": 13
},
{
    "domain": ".douyin.com",
    "expirationDate": 1788877426.99509,
    "hostOnly": False,
    "httpOnly": False,
    "name": "passport_csrf_token_default",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "f124f72879ab0f16ed6eb57a56f320e0",
    "id": 14
},
{
    "domain": ".douyin.com",
    "expirationDate": 1784298225.479195,
    "hostOnly": False,
    "httpOnly": False,
    "name": "strategyABtestKey",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "%221783693425.478%22",
    "id": 15
},
{
    "domain": ".douyin.com",
    "expirationDate": 1784299684.71047,
    "hostOnly": False,
    "httpOnly": False,
    "name": "stream_recommend_feed_params",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A1280%2C%5C%22screen_height%5C%22%3A720%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A8%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A100%7D%22",
    "id": 16
},
{
    "domain": ".douyin.com",
    "expirationDate": 1814798880.766348,
    "hostOnly": False,
    "httpOnly": True,
    "name": "ttwid",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "1%7CIgI4UI3CRsrHWZLAlJCj4fdijQsn_ZcSwuvIEhoaQi4%7C1783693813%7C4929017a87278cc15e91562bff2ff3687f095e2a25867de1e48fb399b6a5fb5b",
    "id": 17
},
{
    "domain": ".douyin.com",
    "expirationDate": 1818253458.787208,
    "hostOnly": False,
    "httpOnly": False,
    "name": "UIFID",
    "path": "/",
    "sameSite": "unspecified",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "599531c2d0c6d0ef0aa9c3ee38b4d46f988bdec21e42bd2919803ff63c227dd109b911e39726fbe07fb6c42dadf24a7b28d8275f45de9d8b1758921c9cb6711006d9c63ccf574f3d919b92435cdb2de599c4d39d21e36acdbe041d132d0c7d19d7bca612df1027d8947048d948eca805009b5568aaced612d8e1a071aded740966b447fabc8473fe0de3f63789894390d694d2829396dc22adc19ffed3f1a571",
    "id": 18
},
{
    "domain": ".douyin.com",
    "expirationDate": 1818253414.437183,
    "hostOnly": False,
    "httpOnly": False,
    "name": "UIFID_TEMP",
    "path": "/",
    "sameSite": "unspecified",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "599531c2d0c6d0ef0aa9c3ee38b4d46f988bdec21e42bd2919803ff63c227dd109b911e39726fbe07fb6c42dadf24a7bdcb7ab616721e58391de05f29f24118899424dd5654749dc82222ea8e7143af2",
    "id": 19
},
{
    "domain": "www.douyin.com",
    "hostOnly": True,
    "httpOnly": False,
    "name": "",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "douyin.com",
    "id": 20
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1783695213.416261,
    "hostOnly": True,
    "httpOnly": False,
    "name": "__ac_nonce",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "06a51006400386806bc65",
    "id": 21
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1815229413,
    "hostOnly": True,
    "httpOnly": False,
    "name": "__ac_signature",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "_02B4Z6wo00f016dhK5AAAIDDJO5Whfq4RwunQS8AAIOR48",
    "id": 22
},
{
    "domain": "www.douyin.com",
    "hostOnly": True,
    "httpOnly": False,
    "name": "architecture",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "amd64",
    "id": 23
},
{
    "domain": "www.douyin.com",
    "hostOnly": True,
    "httpOnly": False,
    "name": "device_web_cpu_core",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "8",
    "id": 24
},
{
    "domain": "www.douyin.com",
    "hostOnly": True,
    "httpOnly": False,
    "name": "device_web_memory_size",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "8",
    "id": 25
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1784299684,
    "hostOnly": True,
    "httpOnly": False,
    "name": "dy_sheight",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "720",
    "id": 26
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1784299684,
    "hostOnly": True,
    "httpOnly": False,
    "name": "dy_swidth",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "1280",
    "id": 27
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1818253424,
    "hostOnly": True,
    "httpOnly": False,
    "name": "fpk1",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "U2FsdGVkX19Oo/PKSZ+hVja4g+ZedTjhIgcX9KCEBL64AeenboQy31PovBhJqguqZMO2lqIkkiqkyTLwQYTEEQ==",
    "id": 28
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1818253424,
    "hostOnly": True,
    "httpOnly": False,
    "name": "fpk2",
    "path": "/",
    "sameSite": "no_restriction",
    "secure": True,
    "session": False,
    "storeId": "0",
    "value": "c33c588009b95570bda142ca18d363d2",
    "id": 29
},
{
    "domain": "www.douyin.com",
    "expirationDate": 1788877415,
    "hostOnly": True,
    "httpOnly": False,
    "name": "s_v_web_id",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": False,
    "storeId": "0",
    "value": "verify_mrf107yd_gbU4la5R_i33D_4PwP_9ja4_yg3kevcRNdf9",
    "id": 30
},
{
    "domain": "www.douyin.com",
    "hostOnly": True,
    "httpOnly": False,
    "name": "x-web-secsdk-uid",
    "path": "/",
    "sameSite": "unspecified",
    "secure": False,
    "session": True,
    "storeId": "0",
    "value": "88e90f39-561f-42e6-9db8-776a831e2b3c",
    "id": 31
}
]

# Viết script ghi cookies
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cookie_file_path = os.path.join(project_root, "cookies.txt")

with open(cookie_file_path, "w", encoding="utf-8") as f:
    f.write("# Netscape HTTP Cookie File\n\n")
    for cookie in cookies_json:
        domain = cookie.get("domain", "")
        if not domain:
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = cookie.get("path", "/")
        secure = "TRUE" if cookie.get("secure", False) else "FALSE"
        
        expires = cookie.get("expirationDate")
        if expires is None:
            expires = int(time.time()) + 315360000
        else:
            expires = int(expires)
            
        name = cookie.get("name", "")
        value = cookie.get("value", "")
        
        # Bỏ qua cookie không có tên hợp lệ
        if not name and value == "douyin.com":
            continue
            
        f.write(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")

print(f"Ghi thành công cookies.txt tại {cookie_file_path}")
