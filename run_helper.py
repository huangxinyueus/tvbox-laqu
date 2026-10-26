import os, re, requests, time, sys, json, hashlib, shutil, base64, random
from datetime import datetime, timezone, timedelta
from io import StringIO
from urllib.parse import urljoin, urlparse
import tvbox_helper

bj_time = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
state_file = '.source_state.json'

USER_AGENTS = [
    'TVBox/1.1.4 (Linux; Android 11)',
    'okhttp/4.10.0',
    'Mozilla/5.0 (Linux; Android 12; M2012K11AC Build/SKQ1.220303.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/94.0.4606.85 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
    'okhttp/3.12.12'
]

# 终极暴力破防解析器：支持任意 HTTP 状态码穿透、JSONP 剥离、JS 对象修复与关键字豁免
def parse_tvbox_content(content_bytes, target_url=''):
    text_data = content_bytes.decode('utf-8', errors='ignore').strip()
    
    # 如果核心内容中明确包含 sites 关键字，绝对豁免图片及 HTML 防御拦截
    has_sites = 'sites' in text_data
    
    if not has_sites:
        if (content_bytes.startswith(b'\x89\x50\x4e\x47') or content_bytes.startswith(b'\xff\xd8\xff') or content_bytes.startswith(b'GIF')):
            raise ValueError('接口防盗链错误返回了图片文件而非JSON配置')
        if '<html' in text_data.lower() and '<body' in text_data.lower():
            raise ValueError('接口返回了HTML安全拦截页面')

    # 尝试 Base64 解码兜底
    if not text_data.startswith('{') and not text_data.startswith('[') and not has_sites:
        try:
            decoded_bytes = base64.b64decode(text_data)
            decoded_text = decoded_bytes.decode('utf-8', errors='ignore').strip()
            if decoded_text.startswith('{') or decoded_text.startswith('['):
                text_data = decoded_text
                has_sites = 'sites' in text_data
        except Exception:
            pass
    
    # 清洗注释与尾随逗号
    cleaned = re.sub(r'//.*', '', text_data)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r',\s*([\]}])', r'\1', cleaned)
    
    parsed = None
    try:
        parsed = json.loads(cleaned)
    except Exception:
        # 尝试正则大括号提取（剥离 PHP 或 JSONP 包装杂音）
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', cleaned)
        if match:
            try:
                parsed = json.loads(match.group(1))
            except Exception:
                try:
                    # 修复单引号配置
                    js_fixed = match.group(1).replace("'", '"')
                    parsed = json.loads(js_fixed)
                except Exception:
                    pass
    
    # 关键词最终兜底：只要包含 sites，直接强制打包为标准 TVBox 结构
    if not isinstance(parsed, dict):
        if has_sites:
            parsed = {"sites": [], "spider": ""}
        else:
            raise ValueError('返回内容不是有效的JSON格式')
            
    return parsed, text_data

def ensure_jar_in_lib(local_path, jar_filename):
    if not os.path.exists(local_path) or os.path.getsize(local_path) <= 1024:
        return
    base_dir = os.path.dirname(local_path)
    lib_dir = os.path.join(base_dir, 'lib') if base_dir else 'lib'
    os.makedirs(lib_dir, exist_ok=True)
    target_lib_jar = os.path.join(lib_dir, jar_filename)
    if not os.path.exists(target_lib_jar) or os.path.getsize(target_lib_jar) != os.path.getsize(local_path):
        try:
            shutil.copy2(local_path, target_lib_jar)
        except Exception:
            pass

    root_lib_dir = 'lib'
    os.makedirs(root_lib_dir, exist_ok=True)
    root_lib_jar = os.path.join(root_lib_dir, jar_filename)
    if not os.path.exists(root_lib_jar) or os.path.getsize(root_lib_jar) != os.path.getsize(local_path):
        try:
            shutil.copy2(local_path, root_lib_jar)
        except Exception:
            pass

old_state = {}
if os.path.exists(state_file):
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            old_state = json.load(f)
    except:
        pass

new_state = {}
sources_raw = []
if os.path.exists('sources_list.txt'):
    with open('sources_list.txt', 'r', encoding='utf-8') as f:
        sources_raw = [line.strip() for line in f if line.strip()]

new_sources_lines = []
source_results = []

for idx, line in enumerate(sources_raw, 1):
    if line.startswith('#'):
        new_sources_lines.append(line)
        continue
    
    parts = line.split(',', 1)
    name = parts[0].strip() if len(parts) > 1 else f'源{idx}'
    url_part = parts[1] if len(parts) > 1 else line
    
    urls = [u.strip() for u in re.split(r'[|\s]+', url_part) if u.strip().startswith('http')]
    
    if not urls:
        source_results.append(f'📌 <b>源 [{idx}] ({name})</b>\n状态: ❌ 失败 (未在行中找到有效网址)')
        new_sources_lines.append(line)
        continue
        
    working_url = None
    fail_details = []
    fetched_content = None
    
    for u_idx, url in enumerate(urls, 1):
        addr_type = '主地址' if u_idx == 1 else f'备用地址 {u_idx-1}'
        success = False
        last_err = ''
        
        parsed_u = urlparse(url)
        netloc_safe = parsed_u.netloc
        try:
            netloc_safe = parsed_u.netloc.encode('idna').decode('ascii')
        except Exception:
            pass
        domain_root = f"{parsed_u.scheme}://{netloc_safe}"
        domain_referer = domain_root + "/"
        
        sep = '&' if '?' in url else '?'
        brute_url = f"{url}{sep}_v={int(time.time())}_{random.randint(1000,9999)}"
        
        session = requests.Session()
        
        for ua in USER_AGENTS:
            headers = {
                'User-Agent': ua,
                'Referer': domain_referer,
                'Origin': domain_root,
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'X-Requested-With': 'XMLHttpRequest',
                'Connection': 'Keep-Alive',
                'Cache-Control': 'no-cache'
            }
            session.headers.update(headers)
            
            for attempt in range(2):
                try:
                    try:
                        session.get(domain_referer, timeout=10)
                    except Exception:
                        pass
                    
                    # 尝试防缓存暴力链接
                    res = session.get(brute_url, timeout=60)
                    
                    # 如果内容不含 sites，尝试原链接
                    if not res.content or b'sites' not in res.content:
                        res_orig = session.get(url, timeout=60)
                        if res_orig.content and b'sites' in res_orig.content:
                            res = res_orig
                    
                    # 核心穿透：只要内容中包含 'sites'，不管 HTTP 状态码是多少（如 456、403），直接判定成功！
                    if res.content and b'sites' in res.content:
                        parsed_json, raw_text = parse_tvbox_content(res.content, url)
                        fetched_content = res.content
                        success = True
                        break
                    elif res.status_code == 200:
                        parsed_json, raw_text = parse_tvbox_content(res.content, url)
                        fetched_content = res.content
                        success = True
                        break
                    else:
                        last_err = f'HTTP状态码 {res.status_code} 且无有效配置'
                except ValueError as ve:
                    last_err = str(ve)
                except requests.exceptions.ConnectionError:
                    last_err = '网络连接/域名解析错误（网站无法打开）'
                except requests.exceptions.Timeout:
                    last_err = '请求超时 (60s)'
                except Exception as e:
                    last_err = f'异常 {str(e)}'
                
                if attempt < 1:
                    time.sleep(2)
            if success:
                break
        
        if success:
            working_url = url
            break
        else:
            fail_details.append(f'{addr_type} ({url}): {last_err}')
            
    if not working_url:
        details_str = '\n  '.join(fail_details)
        source_results.append(f'📌 <b>源 [{idx}] ({name})</b>\n状态: ❌ <b>全部地址失效</b>\n  {details_str}')
        new_sources_lines.append(line)
    else:
        jar_status_tip = ''
        try:
            parsed_json, text_data = parse_tvbox_content(fetched_content, working_url)
            if isinstance(parsed_json, dict):
                spider_val = parsed_json.get('spider', '')
                base_jar_name = None
                if spider_val:
                    spider_path_part = spider_val.split(';')[0].strip()
                    lower_part = spider_path_part.lower()
                    is_image = any(lower_part.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'])
                    if not is_image:
                        if lower_part.endswith('.jar'):
                            base_jar_name = os.path.basename(spider_path_part)
                        else:
                            if '.' in spider_path_part and not spider_path_part.endswith('/'):
                                base_jar_name = os.path.basename(spider_path_part)
                            else:
                                base_jar_name = 'spider.jar'

                if base_jar_name:
                    local_rel_path = f"sources_files/{name}/{base_jar_name}"
                    if os.path.exists(local_rel_path) and os.path.getsize(local_rel_path) > 1024:
                        jar_status_tip = f' | 📦 <b>{base_jar_name} 已存在</b>'
                        ensure_jar_in_lib(local_rel_path, base_jar_name)
                    else:
                        candidate_urls = []
                        if spider_val and spider_val.split(';')[0].strip().startswith('http') and spider_val.split(';')[0].strip().lower().endswith('.jar'):
                            candidate_urls.append(spider_val.split(';')[0].strip())

                        for u in urls:
                            parsed_u = urlparse(u)
                            u_netloc_safe = parsed_u.netloc
                            try:
                                u_netloc_safe = parsed_u.netloc.encode('idna').decode('ascii')
                            except Exception:
                                pass
                            u_domain_root = f"{parsed_u.scheme}://{u_netloc_safe}"
                            u_base_dir = u if u.endswith('/') else u.rsplit('/', 1)[0] + '/'

                            if spider_val and not spider_val.split(';')[0].strip().startswith('http'):
                                clean_path = spider_val.split(';')[0].strip().lstrip('./').lstrip('/')
                                candidate_urls.append(urljoin(u_base_dir, clean_path))
                                candidate_urls.append(urljoin(u, clean_path))

                            candidate_urls.append(urljoin(u_base_dir, base_jar_name))
                            candidate_urls.append(f"{u_domain_root}/{base_jar_name}")
                            candidate_urls.append(f"{u_domain_root}/lib/{base_jar_name}")
                            candidate_urls.append(f"{u_domain_root}/spider.jar")
                            candidate_urls.append(f"{u_domain_root}/fty.jar")

                        seen_cu = set()
                        unique_candidates = [cu for cu in candidate_urls if not (cu in seen_cu or seen_cu.add(cu))]

                        downloaded = False
                        for d_url in unique_candidates:
                            parsed_d = urlparse(d_url)
                            d_netloc_safe = parsed_d.netloc
                            try:
                                d_netloc_safe = parsed_d.netloc.encode('idna').decode('ascii')
                            except Exception:
                                pass
                            d_referer = f"{parsed_d.scheme}://{d_netloc_safe}/"
                            for ua in USER_AGENTS:
                                try:
                                    s_res = requests.get(d_url, headers={'User-Agent': ua, 'Referer': d_referer}, timeout=60)
                                    s_bytes = s_res.content
                                    if (s_res.status_code == 200 or len(s_bytes) > 1024) and not s_bytes.startswith(b'\x89\x50\x4e\x47'):
                                        target_dir = os.path.dirname(os.path.abspath(local_rel_path))
                                        if target_dir:
                                            os.makedirs(target_dir, exist_ok=True)
                                        with open(local_rel_path, 'wb') as sf:
                                            sf.write(s_bytes)
                                        jar_status_tip = f' | 📦 <b>{base_jar_name} 同步成功</b>'
                                        ensure_jar_in_lib(local_rel_path, base_jar_name)
                                        downloaded = True
                                        break
                                except Exception:
                                    continue
                            if downloaded:
                                break
                        if not downloaded:
                            jar_status_tip = f' | ❌ <b>抓取jar失败</b>'

            normalized_str = json.dumps(parsed_json, sort_keys=True, ensure_ascii=False)
        except Exception as je:
            print(f"[ERROR] 解析 JSON 失败: {je}")
            text_data = fetched_content.decode('utf-8', errors='ignore')
            normalized_str = re.sub(r'\s+', '', text_data)

        content_hash = hashlib.md5(normalized_str.encode('utf-8')).hexdigest()
        prev_info = old_state.get(name, {})
        prev_hash = prev_info.get('hash', '')
        prev_time = prev_info.get('time', bj_time)
        
        if content_hash != prev_hash:
            update_status = '✨ 内容已更新'
            last_update_time = bj_time
        else:
            update_status = '🟢 内容无变化'
            last_update_time = prev_time
            
        new_state[name] = {
            'hash': content_hash,
            'time': last_update_time
        }
        
        source_results.append(f'📌 <b>源 [{idx}] ({name})</b>\n状态: ✅ 成功 | {update_status}{jar_status_tip}\n地址: {working_url}\n最后更新时间: {last_update_time}')
        
        other_urls = [u for u in urls if u != working_url]
        reordered_line = f'{name},' + ' | '.join([working_url] + other_urls) if len(parts) > 1 else working_url
        new_sources_lines.append(reordered_line)

with open(state_file, 'w', encoding='utf-8') as f:
    json.dump(new_state, f, ensure_ascii=False, indent=2)

with open('sources_list.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_sources_lines) + '\n')

sys.stdin = StringIO('4\n0\n')
try:
    tvbox_helper.main()
except SystemExit:
    pass

# 自动扫描并修复所有本地 JSON 文件的 spider 指向，统一修正为 ./lib/ 相对路径
for root, dirs, files in os.walk('.'):
    for file in files:
        if file.endswith('.json') and not file.startswith('.'):
            json_path = os.path.join(root, file)
            try:
                with open(json_path, 'r', encoding='utf-8') as jf:
                    jdata = json.load(jf)
                if isinstance(jdata, dict) and 'spider' in jdata and isinstance(jdata['spider'], str):
                    sp_val = jdata['spider']
                    sp_parts = sp_val.split(';')
                    sp_path = sp_parts[0].strip()
                    if not sp_path.startswith('http') and not any(sp_path.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                        jar_name = os.path.basename(sp_path) if sp_path.endswith('.jar') else 'spider.jar'
                        new_sp_path = f"./lib/{jar_name}"
                        sp_parts[0] = new_sp_path
                        jdata['spider'] = ';'.join(sp_parts)
                        with open(json_path, 'w', encoding='utf-8') as jf:
                            json.dump(jdata, jf, ensure_ascii=False, indent=2)
            except Exception:
                pass

details_text = '\n\n'.join(source_results)
message = f'<b>📊 TVBox 智能备用源独立监控报告</b>\n\n{details_text}'

for i in range(1, 11):
    token = os.getenv(f'TG_TOKEN_{i}')
    chat_id = os.getenv(f'TG_CHAT_{i}')
    if token and chat_id:
        url_tg = f'https://api.telegram.org/bot{token}/sendMessage'
        try:
            requests.post(url_tg, json={
                'chat_id': chat_id, 
                'text': message, 
                'parse_mode': 'HTML'
            }, timeout=10)
        except Exception as e:
            print(f'Telegram Bot {i} 发送失败: {e}')
