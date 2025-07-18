import requests
from urllib.parse import urlparse
import ipaddress
import os

def load_source_urls():
    """从data/url.txt文件中加载源地址列表"""
    urls = []
    file_path = os.path.join("data", "url.txt")
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
    except Exception as e:
        print(f"读取源地址文件时出错: {str(e)}")
    return urls

def process_ip(ip: str) -> str:
    """处理IP地址，将最后一位改为1"""
    parts = ip.split('.')
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        return f"{'.'.join(parts[:3])}.1"
    return ip  # 如果格式错误则保持原样

def main():
    results = set()
    source_urls = load_source_urls()

    if not source_urls:
        print("没有可用的源地址，程序退出")
        return

    for url in source_urls:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            
            for line in resp.text.splitlines():
                line = line.strip()
                if ",http" in line and "/tsfile/" in line:
                    try:
                        # 分割频道名和URL
                        _, url_part = line.split(",", 1)
                        parsed = urlparse(url_part)
                        
                        # 提取IP和端口
                        if not parsed.port or not parsed.hostname:
                            continue
                            
                        # 验证是否为IPv4地址
                        try:
                            ipaddress.IPv4Address(parsed.hostname)
                        except ipaddress.AddressValueError:
                            continue
                            
                        # 处理IP地址
                        processed_ip = process_ip(parsed.hostname)
                        # 格式化为完整的HTTP URL
                        results.add(f"http://{processed_ip}:{parsed.port}")
                        
                    except Exception as e:
                        print(f"处理行时出错: {line} -> {str(e)}")
                        
        except Exception as e:
            print(f"获取源数据失败: {url} -> {str(e)}")

    # 确保data目录存在
    os.makedirs("data", exist_ok=True)
    
    # 写入文件
    with open("data/jd.ip", "w", encoding="utf-8") as f:
        for item in sorted(results):
            f.write(f"{item}\n")

if __name__ == "__main__":
    main()