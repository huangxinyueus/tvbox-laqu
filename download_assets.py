import os
import base64
import json
import re
import requests

def select_or_input_folder(require_api_converted=False):
    sources_base = "./sources_files"
    os.makedirs(sources_base, exist_ok=True)
    
    # 筛选符合条件的文件夹
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

def step1_download_and_convert():
    print("\n--- 【步骤 1：下载并解密订阅源】 ---")
    folder_name = select_or_input_folder(require_api_converted=False)
    if not folder_name:
        print("↩️ 已取消操作，返回主菜单。")
        return None
        
    target_url = input("请输入要下载的 TVBox 订阅链接 (输入 b 返回): ").strip()
    if target_url.lower() == 'b':
        print("↩️ 已取消操作，返回主菜单。")
        return None
    if not target_url:
        print("❌ 订阅链接不能为空！")
        return None

    target_dir = os.path.join("./sources_files", folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    api_path = os.path.join(target_dir, "api.json")
    output_path = os.path.join(target_dir, "api_改.json")
    
    headers = {"User-Agent": "okhttp/4.1.0"}
    
    print(f"📁 目标保存目录: {target_dir}")
    print("正在下载原始文件...")
    try:
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        with open(api_path, 'wb') as f:
            f.write(response.content)
        print(f"✅ 原始文件已下载至: {api_path}")
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        return None

    print("正在解析并转换格式...")
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
            
        print(f"🎉 成功生成: {output_path}")
        return folder_name
    except Exception as e:
        print(f"❌ 解析转换失败: {e}")
        return None


def step2_download_assets(folder_name=None):
    print("\n--- 【步骤 2：依据已有 api_改.json 下载关联资源】 ---")
    if not folder_name:
        folder_name = select_or_input_folder(require_api_converted=True)
        if not folder_name:
            print("↩️ 已取消操作，返回主菜单。")
            return
    
    target_dir = os.path.join("./sources_files", folder_name)
    api_path = os.path.join(target_dir, "api_改.json")
    local_json_path = os.path.join(target_dir, "api_本地版.json")
    
    if not os.path.exists(api_path):
        print(f"❌ 未找到 {api_path}，请先执行步骤 1 生成该文件！")
        return
        
    print(f"正在读取 {api_path} ...")
    with open(api_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    headers = {"User-Agent": "okhttp/4.1.0"}
    
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

    # 1. 强制下载并重命名 Spider 为 spider.jar
    spider = data.get("spider", "")
    if spider:
        parts = spider.split(';')
        url = parts[0]
        if url.startswith("http://") or url.startswith("https://"):
            save_path = os.path.join(target_dir, "lib", "spider.jar")
            if download_file(url, save_path):
                parts[0] = "./lib/spider.jar"
                data["spider"] = ';'.join(parts)

    # 2. 下载扩展 (ext)
    for site in data.get("sites", []):
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

    # 3. 下载直播源 (lives)
    for live in data.get("lives", []):
        url = live.get("url", "")
        if url.startswith("http://") or url.startswith("https://"):
            filename = os.path.basename(url.split('?')[0])
            if not filename or '.' not in filename: 
                filename = "live.m3u"
            save_path = os.path.join(target_dir, "live", filename)
            if download_file(url, save_path):
                live["url"] = f"./live/{filename}"

    # 生成本地版配置
    with open(local_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"\n==================================================")
    print(f"🎉 关联资源全部下载完毕！")
    print(f"📁 目标目录: {target_dir}")
    print(f"📄 离线本地版配置: {local_json_path}")
    print(f"==================================================")


def main():
    while True:
        print("\n==================================================")
        print("       TVBox 本地便携免安装助手（返回菜单版）       ")
        print("==================================================")
        print("1. 下载并解密订阅源 (输入链接 -> 生成 api_改.json)")
        print("2. 依据已有 api_改.json 下载关联资源并本地化 (选择文件夹即可)")
        print("3. 一键完整处理 (连续执行 步骤1 + 步骤2)")
        print("0. 退出程序")
        print("--------------------------------------------------")
        
        choice = input("请选择操作编号 [0-3]: ").strip()
        
        if choice == '1':
            step1_download_and_convert()
        elif choice == '2':
            step2_download_assets()
        elif choice == '3':
            folder = step1_download_and_convert()
            if folder:
                step2_download_assets(folder)
        elif choice == '0':
            print("👋 感谢使用，再见！")
            break
        else:
            print("❌ 无效的输入，请输入 0、1、2 或 3！")

if __name__ == '__main__':
    main()