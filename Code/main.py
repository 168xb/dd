import asyncio
import aiohttp
import re
import datetime
import requests
import eventlet
import os
import time
import threading
from queue import Queue
from collections import defaultdict

eventlet.monkey_patch()

# 从data/jd.ip文件中读取URL列表
with open('data/jd.ip', 'r', encoding='utf-8') as f:
    urls = [line.strip() for line in f if line.strip()]

# 全局配置
CONFIG = {
    'timeout': 1.5,  # 基本超时时间
    'concurrency': 300,  # 并发限制
    'max_workers': 15,  # 工作线程数
    'result_counter': 8,  # 每个频道最大保留结果数
    'min_speed': 0.001,  # 最低速度限制(MB/s)
    'max_speed': 100,    # 最高速度限制(MB/s)
}

async def modify_urls(url):
    """生成修改后的URL列表"""
    modified_urls = []
    ip_start_index = url.find("//") + 2
    ip_end_index = url.find(":", ip_start_index)
    base_url = url[:ip_start_index]
    ip_address = url[ip_start_index:ip_end_index]
    port = url[ip_end_index:]
    ip_end = "/iptv/live/1000.json?key=txiptv"
    
    # 只生成最后一位1-255的IP
    for i in range(1, 256):
        modified_ip = f"{ip_address[:-1]}{i}"
        modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
        modified_urls.append(modified_url)
    return modified_urls

async def is_url_accessible(session, url, semaphore):
    """检查URL是否可访问"""
    async with semaphore:
        try:
            async with session.get(url, timeout=1) as response:
                if response.status == 200:
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{current_time} {url}")
                    return url
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            pass
    return None

async def check_urls(session, urls, semaphore):
    """批量检查URL可访问性"""
    tasks = []
    for url in urls:
        url = url.strip()
        modified_urls = await modify_urls(url)
        for modified_url in modified_urls:
            task = asyncio.create_task(is_url_accessible(session, modified_url, semaphore))
            tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    return [result for result in results if result]

def normalize_channel_name(name):
    """标准化频道名称"""
    name = name.replace("cctv", "CCTV").replace("中央", "CCTV").replace("央视", "CCTV")
    name = re.sub(r"(高清|超高|HD|标清|频道|-| |PLUS|＋|\(|\))", "", name)
    name = re.sub(r"CCTV(\d+)台", r"CCTV\1", name)
    
    # CCTV频道标准化
    cctv_mappings = {
        "CCTV1综合": "CCTV1", "CCTV2财经": "CCTV2", "CCTV3综艺": "CCTV3",
        "CCTV4国际": "CCTV4", "CCTV4中文国际": "CCTV4", "CCTV4欧洲": "CCTV4",
        "CCTV5体育": "CCTV5", "CCTV6电影": "CCTV6", "CCTV7军事": "CCTV7",
        "CCTV7军农": "CCTV7", "CCTV7农业": "CCTV7", "CCTV7国防军事": "CCTV7",
        "CCTV8电视剧": "CCTV8", "CCTV9记录": "CCTV9", "CCTV9纪录": "CCTV9",
        "CCTV10科教": "CCTV10", "CCTV11戏曲": "CCTV11", "CCTV12社会与法": "CCTV12",
        "CCTV13新闻": "CCTV13", "CCTV新闻": "CCTV13", "CCTV14少儿": "CCTV14",
        "CCTV15音乐": "CCTV15", "CCTV16奥林匹克": "CCTV16", "CCTV17农业农村": "CCTV17",
        "CCTV17农业": "CCTV17", "CCTV5+体育赛视": "CCTV5+", "CCTV5+体育赛事": "CCTV5+",
        "CCTV5+体育": "CCTV5+"
    }
    
    for old, new in cctv_mappings.items():
        name = name.replace(old, new)
    
    return name

async def fetch_json(session, url, semaphore):
    """获取并处理JSON数据"""
    async with semaphore:
        try:
            ip_start_index = url.find("//") + 2
            ip_dot_start = url.find(".") + 1
            ip_index_second = url.find("/", ip_dot_start)
            base_url = url[:ip_start_index]
            ip_address = url[ip_start_index:ip_index_second]
            url_x = f"{base_url}{ip_address}"

            async with session.get(url, timeout=1) as response:
                json_data = await response.json()
                results = []
                
                for item in json_data.get('data', []):
                    if isinstance(item, dict):
                        name = item.get('name', '')
                        urlx = item.get('url', '')
                        
                        if not name or not urlx:
                            continue
                            
                        if ',' in urlx:
                            continue  # 跳过无效URL
                            
                        name = normalize_channel_name(name)
                        
                        if 'http' in urlx:
                            urld = urlx
                        else:
                            urld = f"{url_x}{urlx}"
                            
                        results.append(f"{name},{urld}")
                
                return results
                
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
            return []

async def process_valid_urls(session, valid_urls, semaphore):
    """处理所有有效URL"""
    all_results = []
    tasks = [asyncio.create_task(fetch_json(session, url, semaphore)) for url in valid_urls]
    results = await asyncio.gather(*tasks)
    
    for sublist in results:
        all_results.extend(sublist)
    
    return all_results

def test_channel_speed(channel_name, channel_url):
    """测试频道速度"""
    try:
        channel_url_t = channel_url.rstrip(channel_url.split('/')[-1])
        response = requests.get(channel_url, timeout=1)
        lines = response.text.strip().split('\n')
        
        if not lines:
            return None
            
        ts_lists = [line.split('/')[-1] for line in lines if not line.startswith('#')]
        if not ts_lists:
            return None
            
        ts_lists_0 = ts_lists[0].rstrip(ts_lists[0].split('.ts')[-1])
        ts_url = channel_url_t + ts_lists[0]

        start_time = time.time()
        content = requests.get(ts_url, timeout=1).content
        end_time = time.time()
        
        if not content:
            return None
            
        response_time = end_time - start_time
        file_size = len(content)
        download_speed = file_size / response_time / 1024 / 1024  # MB/s
        
        # 速度限制在0.001-100 MB/s之间
        normalized_speed = max(min(download_speed, CONFIG['max_speed']), CONFIG['min_speed'])
        
        # 清理临时文件
        if os.path.exists(ts_lists_0):
            os.remove(ts_lists_0)
            
        return channel_name, channel_url, f"{normalized_speed:.3f} MB/s"
        
    except:
        return None

def worker(task_queue, results, error_channels, all_results_count):
    """工作线程函数"""
    while True:
        channel_name, channel_url = task_queue.get()
        result = test_channel_speed(channel_name, channel_url)
        
        if result:
            results.append(result)
        else:
            error_channels.append((channel_name, channel_url))
            
        # 计算进度
        processed = len(results) + len(error_channels)
        progress = processed / all_results_count * 100
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{current_time}可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{all_results_count} 个 ,总进度：{progress:.2f} %。")
        
        task_queue.task_done()

def channel_key(channel_name):
    """生成频道排序键"""
    match = re.search(r'\d+', channel_name)
    if match:
        return int(match.group())
    else:
        return float('inf')

def save_results(results):
    """保存结果到文件"""
    # 按频道名称和速度排序
    results.sort(key=lambda x: (x[0], -float(x[2].split()[0])))
    results.sort(key=lambda x: channel_key(x[0]))
    
    # 保存速度结果
    with open("txt/speed_results.txt", 'w', encoding='utf-8') as file:
        for result in results:
            file.write(f"{result[0]},{result[1]},{result[2]}\n")
    
    # 保存分类频道列表
    with open("txt/itvlist.txt", 'w', encoding='utf-8') as file:
        # 央视频道
        file.write('央视频道,#genre#\n')
        cctv_counter = defaultdict(int)
        for name, url, _ in results:
            if 'CCTV' in name:
                if cctv_counter[name] < CONFIG['result_counter']:
                    file.write(f"{name},{url}\n")
                    cctv_counter[name] += 1
        
        # 卫视频道
        file.write('\n卫视频道,#genre#\n')
        ws_counter = defaultdict(int)
        for name, url, _ in results:
            if '卫视' in name and 'CCTV' not in name:
                if ws_counter[name] < CONFIG['result_counter']:
                    file.write(f"{name},{url}\n")
                    ws_counter[name] += 1
        
        # 其他频道
        file.write('\n其他频道,#genre#\n')
        other_counter = defaultdict(int)
        for name, url, _ in results:
            if 'CCTV' not in name and '卫视' not in name and '测试' not in name:
                if other_counter[name] < CONFIG['result_counter']:
                    file.write(f"{name},{url}\n")
                    other_counter[name] += 1

async def main():
    """主函数"""
    # 预处理URL
    x_urls = []
    for url in urls:
        url = url.strip()
        ip_start_index = url.find("//") + 2
        ip_end_index = url.find(":", ip_start_index)
        ip_dot_start = url.find(".") + 1
        ip_dot_second = url.find(".", ip_dot_start) + 1
        ip_dot_three = url.find(".", ip_dot_second) + 1
        base_url = url[:ip_start_index]
        ip_address = url[ip_start_index:ip_dot_three]
        port = url[ip_end_index:]
        modified_ip = f"{ip_address}1"
        x_url = f"{base_url}{modified_ip}{port}"
        x_urls.append(x_url)
    
    unique_urls = list(set(x_urls))  # 去重

    # 检查URL可访问性
    semaphore = asyncio.Semaphore(CONFIG['concurrency'])
    async with aiohttp.ClientSession() as session:
        valid_urls = await check_urls(session, unique_urls, semaphore)
        all_results = await process_valid_urls(session, valid_urls, semaphore)
    
    # 多线程测试频道速度
    task_queue = Queue()
    results = []
    error_channels = []
    
    # 创建工作线程
    for _ in range(CONFIG['max_workers']):
        t = threading.Thread(
            target=worker,
            args=(task_queue, results, error_channels, len(all_results)),
            daemon=True
        )
        t.start()
    
    # 添加任务到队列
    for result in all_results:
        channel_name, channel_url = result.split(',')
        task_queue.put((channel_name, channel_url))
    
    # 等待所有任务完成
    task_queue.join()
    
    # 保存结果
    save_results(results)

if __name__ == "__main__":
    asyncio.run(main())