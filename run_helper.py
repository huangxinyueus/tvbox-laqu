import os, re, requests, time, sys, json, hashlib, shutil, base64, zlib, gzip, random
from datetime import datetime, timezone, timedelta
from io import StringIO
from urllib.parse import urljoin, urlparse
import tvbox_helper

bj_time = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
state_file = '.source_state.json'

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Linux; Android 13; V2231A Build/TP1A.220624.014) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.43 Mobile Safari/537.36',
    'TVBox/1.1.4 (Linux; Android 11)',
    'okhttp/4.10.0'
]

# 融合 tvbox_helper 的深度字节解密与 raw_decode 引擎
def parse_tvbox_content(raw_bytes, target_url=''):
    content_candidates = []

    # 0. 尝试提取 PNG 隐写尾椎 (针对防盗链图片包裹JSON的情况)
    if b'IEND' in raw_bytes:
        try:
            iend_pos = raw_bytes.rfind(b'IEND')
            after_iend = raw_bytes[iend_pos + 8:]
            content_candidates.append(after_iend.decode('utf-8', errors='ignore'))
        except Exception:
            pass

    # 1. 尝试 Hex 十六进制转二进制
    try:
        text_preview = raw_bytes[:120].decode('utf-8', errors='ignore').strip()
        if text_preview.startswith('2423') or (len(text_preview) > 50 and all(c in '0123456789abcdefABCDEF' for c in text_preview[:100])):
            raw_bytes = bytes.fromhex(text_preview)
    except Exception:
        pass

    # 2. 剥离 $# 魔术头
    try:
        if raw_bytes.startswith(b'$#'):
            idx_end = raw_bytes.find(b'#$', 2)
            if idx_end != -1:
                raw_bytes = raw_bytes[idx_end + 2:]
    except Exception:
        pass

    # 3. 多路解压与解码尝试
    try:
        content_candidates.append(raw_bytes.decode('utf-8', errors='ignore'))
    except:
        pass
        
    try:
        content_candidates.append(zlib.decompress(raw_bytes).decode('utf-8', errors='ignore'))
    except:
        try:
            content_candidates.append(gzip.decompress(raw_bytes).decode('utf-8', errors='ignore'))
        except:
            pass

    # 4. 暴力搜索整个文件中的所有长 Base64 片段并尝试解码
    try:
        full_str = raw_bytes.decode('latin1', errors='ignore')
        b64_matches = re.findall(r'[A-Za-z0-9+/=]{30,}', full_str)
        for b64_str in b64_matches:
            try:
                dec = base64.b64decode(b64_str.encode('utf-8'))
                content_candidates.append(dec.decode('utf-8', errors='ignore'))
                try:
                    content_candidates.append(zlib.decompress(dec).decode('utf-8', errors='ignore'))
                except:
                    pass
            except:
                pass
    except:
        pass

    content_candidates.append(raw_bytes.decode('latin1', errors='ignore'))
    combined_content = "\n".join(content_candidates)
    
    # 清理注释行及反爬干扰文本
    clean_lines = [line for line in combined_content.splitlines() if not line.strip().startswith('//') and '高抬贵手' not in line]
    clean_content = '\n'.join(clean_lines).strip()

    # 5. 全局遍历所有 '{' 或 '[' 位置，利用 raw_decode 寻找合法的 TVBox 配置
    possible_indices = [i for i, char in enumerate(clean_content) if char in ('{', '[')]
    json_data = None
    
    for idx in possible_indices:
        try:
            data, _ = json.JSONDecoder().raw_decode(clean_content, idx)
            if isinstance(data, (dict, list)) and len(data) > 0:
                if isinstance(data, dict) and any(k in data for k in ('sites', 'spider', 'lives', 'channels', 'parses')):
                    json_data = data
                    break
                elif json_data is None and isinstance(data, dict):
                    json_data = data
        except Exception:
            continue

    if json_data is None and 'sites' in clean_content:
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', clean_content)
        if match:
            try:
                json_data = json.loads(match.group(1))
            except Exception:
                pass

    if json_data is None:
        raise ValueError("未能提取到合法的 JSON 配置对象")
        
    return json_data, clean_content

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
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
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
                    
                    res = session.get(brute_url, timeout=60, verify=False)
                    if not res.content or b'sites' not in res.content:
                        res_orig = session.get(url, timeout=60, verify=False)
                        if res_orig.content:
                            res = res_orig
                    
                    # 任意状态码穿透（完美解决 PHP 456 错误码无法抓取的问题）
                    try:
                        parsed_json, raw_text = parse_tvbox_content(res.content, url)
                        fetched_content = res.content
                        success = True
                        break
                    except Exception as inner_ex:
                        if res.status_code == 200:
                            last_err = f'解析失败: {inner_ex}'
                        else:
                            last_err = f'HTTP状态码 {res.status_code}'
                except requests.exceptions.ConnectionError:
                    last_err = '网络连接/域名解析错误'
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
                                    s_res = requests.get(d_url, headers={'User-Agent': ua, 'Referer': d_referer}, timeout=60, verify=False)
                                    s_bytes = s_res.content
                                    if len(s_bytes) > 1024 and not s_bytes.startswith(b'\x89\x50\x4e\x47'):
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
