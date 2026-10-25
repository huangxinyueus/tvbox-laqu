import os
import base64
import json
import re
import requests

def select_or_input_folder(require_api_converted=False):
    sources_base = "./sources_files"
    os.makedirs(sources_base, exist_ok=True)
    
    folders = []
    for f in os.listdir(sources_base):
        f_path = os.path.join(sources_base, f)
        if os.path.isdir(f_path):
            if require_api_converted:
                if os.path.exists(os.path.join(f_path, "api_改.json")):
                    folders.append(f)
            else:
                folders.append(f)
                
    if folders:
        print("\n📁 可用的分类文件夹:")
        for idx, f in enumerate(folders, 1):
            print(f"  [{idx}] {f}")
        print(f"  [0] 手动输入新文件夹名称")
        print(f"  [b] 返回上级菜单")
        
        choice = input("请选择编号、输入 0 或按 b 返回: ").strip().lower()
        if choice == 'b':
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(folders):
            selected = folders[int(choice) - 1]
            print(f"-> 已选择文件夹: {selected}")
            return selected
    else:
        print(f"  [b] 返回上级菜单")
            
    folder_name = input("请输入分类文件夹名称 (输入 b 返回): ").strip()
    if folder_name.lower() == 'b':
        return None
    return folder_name if folder_name else "default_sources"

def process_single_task(folder_name, url_input):
    target_dir = os.path.join("./sources_files", folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    api_path = os.path.join(target_dir, "api.json")
    output_path = os.path.join(target_dir, "api_改.json")
    local_json_path = os.path.join(target_dir, "api_本地版.json")
    
    headers = {"User-Agent": "okhttp/4.1.0"}
    
    # 解析可能存在的多个备用地址（用 | 分隔）
    urls = [u.strip() for u in url_input.split('|') if u.strip()]
    if not urls:
        print(f"❌ 错误：【{folder_name}】未提供有效的订阅链接！")
        return False

    # --- 步骤 1：尝试下载并解密（支持多地址轮流重试） ---
    print(f"\n📁 目标目录: {target_dir}")
    success_download = False
    
    for idx, target_url in enumerate(urls, 1):
        try:
            if len(urls) > 1:
                print(f"正在尝试第 {idx} 个地址 ({target_url}) ...")
            else:
                print(f"正在下载订阅链接...")
                
            response = requests.get(target_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            with open(api_path, 'wb') as f:
                f.write(response.content)
            print(f"  -> ✅ 成功从该地址下载原始文件至: {api_path}")
            success_download = True
            break
        except Exception as e:
            print(f"  -> ⚠️ 地址 {target_url} 下载失败: {e}")
            if idx < len(urls):
                print(f"  -> 🔄 正在自动切换至备用地址...")
            
    if not success_download:
        print(f"  -> ❌ 错误：【{folder_name}】的所有主备用地址均下载失败！")
        return False

    try:
        try:
            with open(api_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            if 'JFIF' in content or '**' in content or len(content.strip().splitlines()) < 5:
                raise Exception("需要Base64解密")
        except Exception:
            with open(api_path, 'r', encoding='latin1') as f:
                raw_content = f.read()
            if '**' in raw_content:
                b64_str = raw_content.split('**')[-1]
            else:
                match = re.search(r'[A-Za-z0-9+/=]{50,}', raw_content)
                b64_str = match.group(0) if match else raw_content
            decoded_bytes = base64.b64decode(b64_str.strip())
            content = decoded_bytes.decode('utf-8', errors='ignore')

        clean_lines = [line for line in content.splitlines() if not line.strip().startswith('//')]
        clean_content = '\n'.join(clean_lines)

        start_idx = clean_content.find('{')
        end_idx = clean_content.rfind('}')
        if start_idx != -1 and end_idx != -1:
            clean_json_str = clean_content[start_idx:end_idx+1]
        else:
            clean_json_str = clean_content

        json_data = json.loads(clean_json_str)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        print(f"  -> ✅ 成功生成: {output_path}")
    except Exception as e:
        print(f"  -> ❌ 解析转换失败: {e}")
        return False

    # --- 步骤 2：下载关联资源并本地化 ---
    print("正在暴力下载关联资源并生成本地版...")
    
    def download_file(url, save_path):
        if "127.0.0.1" in url or "localhost" in url:
            print(f"  -> ⏭️ 跳过本地代理/内部服务地址: {url}")
            return False
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            print(f"📥 下载: {url}")
            res = requests.get(url, headers=headers, timeout=25)
            if res.status_code == 200:
                with open(save_path, 'wb') as sf:
                    sf.write(res.content)
                print(f"  -> ✅ 保存成功: {save_path}")
                return True
        except Exception as e:
            print(f"  -> ❌ 下载失败: {e}")
        return False

    spider = json_data.get("spider", "")
    if spider:
        parts = spider.split(';')
        url = parts[0]
        if url.startswith("http://") or url.startswith("https://"):
            save_path = os.path.join(target_dir, "lib", "spider.jar")
            if download_file(url, save_path):
                parts[0] = "./lib/spider.jar"
                json_data["spider"] = ';'.join(parts)

    for site in json_data.get("sites", []):
        ext = site.get("ext")
        if isinstance(ext, str) and (ext.startswith("http://") or ext.startswith("https://")):
            filename = os.path.basename(ext.split('?')[0]) or "ext_config.txt"
            save_path = os.path.join(target_dir, "lib", filename)
            if download_file(ext, save_path):
                site["ext"] = f"./lib/{filename}"
        elif isinstance(ext, dict):
            for k, v in ext.items():
                if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
                    filename = os.path.basename(v.split('?')[0]) or f"{k}.txt"
                    save_path = os.path.join(target_dir, "lib", filename)
                    if download_file(v, save_path):
                        ext[k] = f"./lib/{filename}"

    for live in json_data.get("lives", []):
        url = live.get("url", "")
        if url.startswith("http://") or url.startswith("https://"):
            filename = os.path.basename(url.split('?')[0])
            if not filename or '.' not in filename: 
                filename = "live.m3u"
            save_path = os.path.join(target_dir, "live", filename)
            if download_file(url, save_path):
                live["url"] = f"./live/{filename}"

    with open(local_json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
        
    print(f"  -> 🎉 【{folder_name}】全部处理完成！本地版配置: {local_json_path}\n")
    return True

def step1_only_download_and_convert():
    print("\n--- 【步骤 1：仅下载并解密订阅源】 ---")
    folder_name = select_or_input_folder(require_api_converted=False)
    if not folder_name:
        print("↩️ 已取消操作，返回主菜单。")
        return
        
    target_url = input("请输入订阅链接（支持用 | 输入多个备用地址，输入 b 返回）: ").strip()
    if target_url.lower() == 'b':
        print("↩️ 已取消操作，返回主菜单。")
        return
    if not target_url:
        print("❌ 订阅链接不能为空！")
        return

    process_single_task(folder_name, target_url)

def step3_one_click_workflow():
    print("\n--- 【步骤 3：一键完整处理单个源】 ---")
    folder_name = select_or_input_folder(require_api_converted=False)
    if not folder_name:
        print("↩️ 已取消操作，返回主菜单。")
        return
        
    target_url = input("请输入订阅链接（支持用 | 输入多个备用地址，输入 b 返回）: ").strip()
    if target_url.lower() == 'b':
        print("↩️ 已取消操作，返回主菜单。")
        return
    if not target_url:
        print("❌ 订阅链接不能为空！")
        return

    process_single_task(folder_name, target_url)

def step4_batch_download_from_txt():
    print("\n--- 【步骤 4：通过 TXT 文件批量下载与本地化】 ---")
    txt_path = "sources_list.txt"
    
    if not os.path.exists(txt_path):
        sample_content = (
            "# 请在下方按“文件夹名称, 主地址 | 备用地址”的格式填写，每行一个源\n"
            "# 以 # 开头的行或空行会被自动忽略\n"
            "# 示例格式（支持多个备用地址用 | 隔开）：\n"
            "饭太硬,https://主地址.com/api.json | https://备用地址.com/api.json\n"
            "其他源,http://main.com/api.json\n"
        )
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(sample_content)
        print(f"📄 未检测到 {txt_path}，已自动为你创建一个示例文本文件！")
        print(f"💡 请打开该文件，填入你的“文件夹名称,链接”后，保存并重新选择选项 4。")
        return

    print(f"📂 正在读取 {txt_path} 中的批量任务...")
    batch_tasks = []
    
    with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if ',' in line:
                parts = line.split(',', 1)
            else:
                parts = line.split(None, 1)
                
            if len(parts) == 2:
                folder_name = parts[0].strip()
                target_url = parts[1].strip()
                if folder_name and target_url:
                    batch_tasks.append((folder_name, target_url))
            else:
                print(f"⚠️ 第 {line_num} 行格式不正确，已跳过: {line}")

    if not batch_tasks:
        print(f"❌ 在 {txt_path} 中没有找到有效的任务配置！")
        return

    print(f"\n🚀 成功加载 {len(batch_tasks)} 个批量任务，开始执行...\n")
    for idx, (folder_name, target_url) in enumerate(batch_tasks, 1):
        print(f"==================================================")
        print(f"🔄 正在处理第 {idx}/{len(batch_tasks)} 个任务: 文件夹【{folder_name}】")
        print(f"==================================================")
        process_single_task(folder_name, target_url)
        
    print(f"🎉 批量下载与本地化全部执行完毕！")


def main():
    while True:
        print("\n==================================================")
        print("       TVBox 本地便携免安装助手（备用地址增强版）     ")
        print("==================================================")
        print("1. 仅下载并解密订阅源 (输入链接 -> 生成 api_改.json)")
        print("2. 依据已有 api_改.json 下载关联资源并本地化 (选择文件夹)")
        print("3. 一键完整处理单个源 (输入文件夹 + 链接 -> 全套本地化)")
        print("4. 批量下载与本地化多个订阅源 (读取 sources_list.txt 文件)")
        print("0. 退出程序")
        print("--------------------------------------------------")
        
        choice = input("请选择操作编号 [0-4]: ").strip()
        
        if choice == '1':
            step1_only_download_and_convert()
        elif choice == '2':
            folder_name = select_or_input_folder(require_api_converted=True)
            if folder_name:
                target_dir = os.path.join("./sources_files", folder_name)
                api_path = os.path.join(target_dir, "api_改.json")
                local_json_path = os.path.join(target_dir, "api_本地版.json")
                if os.path.exists(api_path):
                    with open(api_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    headers = {"User-Agent": "okhttp/4.1.0"}
                    def dl(url, sp):
                        if "127.0.0.1" in url or "localhost" in url:
                            return False
                        try:
                            os.makedirs(os.path.dirname(sp), exist_ok=True)
                            res = requests.get(url, headers=headers, timeout=25)
                            if res.status_code == 200:
                                with open(sp, 'wb') as sf:
                                    sf.write(res.content)
                                return True
                        except:
                            pass
                        return False
                    spider = data.get("spider", "")
                    if spider:
                        p = spider.split(';')
                        if p[0].startswith("http"):
                            if dl(p[0], os.path.join(target_dir, "lib", "spider.jar")):
                                p[0] = "./lib/spider.jar"
                                data["spider"] = ';'.join(p)
                    for site in data.get("sites", []):
                        ext = site.get("ext")
                        if isinstance(ext, str) and ext.startswith("http"):
                            fn = os.path.basename(ext.split('?')[0]) or "ext_config.txt"
                            if dl(ext, os.path.join(target_dir, "lib", fn)):
                                site["ext"] = f"./lib/{fn}"
                        elif isinstance(ext, dict):
                            for k, v in ext.items():
                                if isinstance(v, str) and v.startswith("http"):
                                    fn = os.path.basename(v.split('?')[0]) or f"{k}.txt"
                                    if dl(v, os.path.join(target_dir, "lib", fn)):
                                        ext[k] = f"./lib/{fn}"
                    for live in data.get("lives", []):
                        url = live.get("url", "")
                        if url.startswith("http"):
                            fn = os.path.basename(url.split('?')[0]) or "live.m3u"
                            if dl(url, os.path.join(target_dir, "live", fn)):
                                live["url"] = f"./live/{fn}"
                    with open(local_json_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"🎉 关联资源补下完毕，已生成: {local_json_path}")
                else:
                    print(f"❌ 未找到 {api_path}")
        elif choice == '3':
            step3_one_click_workflow()
        elif choice == '4':
            step4_batch_download_from_txt()
        elif choice == '0':
            print("👋 感谢使用，再见！")
            break
        else:
            print("❌ 无效的输入，请输入 0 到 4 之间的编号！")

if __name__ == '__main__':
    main()