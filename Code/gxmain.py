import asyncio
import aiohttp
import re
import datetime
import requests
import os
import time
import threading
from queue import Queue
from collections import defaultdict

# 全局配置
CONFIG = {
    'timeout': 1.5,           # 请求超时时间(秒)
    'max_concurrent': 300,    # 最大并发请求数
    'max_workers': 15,        # 工作线程数
    'result_counter': 8,      # 每个频道最大保留结果数
    'min_speed': 0.001,       # 最低速度限制(MB/s)
    'max_speed': 100,         # 最高速度限制(MB/s)
    'input_file': 'data/jdgx.ip',  # 输入文件路径
    'output_speed': 'txt/speed_results.txt',  # 速度结果文件
    'output_channels': 'txt/gxtv.txt'  # 频道分类文件
}

def modify_urls(url):
    """生成修改后的URL列表"""
    modified_urls = []
    ip_start_index = url.find("//") + 2
    ip_end_index = url.find(":", ip_start_index)
    base_url = url[:ip_start_index]  # http:// or https://
    ip_address = url[ip_start_index:ip_end_index]
    port = url[ip_end_index:]
    ip_end = "/ZHGXTV/Public/json/live_interface.txt"
    
    # 生成最后一位1-255的IP
    for i in range(1, 256):
        modified_ip = f"{ip_address[:-1]}{i}"
        modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
        modified_urls.append(modified_url)
    return modified_urls

async def is_url_accessible(session, url, semaphore):
    """异步检查URL是否可访问"""
    async with semaphore:
        try:
            async with session.get(url, timeout=CONFIG['timeout']) as response:
                if response.status == 200:
                    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"{current_time} 发现有效服务器: {url}")
                    return url
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
    return None

async def check_urls(session, urls, semaphore):
    """批量检查URL可访问性"""
    tasks = []
    for url in urls:
        url = url.strip()
        modified_urls = modify_urls(url)
        for modified_url in modified_urls:
            task = asyncio.create_task(is_url_accessible(session, modified_url, semaphore))
            tasks.append(task)
    
    results = await asyncio.gather(*tasks)
    return [result for result in results if result]

def normalize_channel_name(name):
    """标准化频道名称"""
    # 基本清理
    name = name.replace("cctv", "CCTV").replace("中央", "CCTV").replace("央视", "CCTV")
    name = re.sub(r"(高清|超清|超高|HD|标清|频道|-| |PLUS|＋|\(|\))", "", name)
    name = re.sub(r"CCTV(\d+)台", r"CCTV\1", name)
    
    # CCTV频道标准化映射
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
        "CCTV5+体育": "CCTV5+", "CCTV足球": "CCTV风云足球", "CCTV赛事": "CCTV5+"
    }
    
    # 其他频道标准化映射
    other_mappings = {
        "上海卫视": "东方卫视", "全纪实": "乐游纪实", "金鹰动画": "金鹰卡通",
        "河南新农村": "河南乡村", "河南法制": "河南法治", "文物宝库": "河南收藏天下",
        "梨园": "河南戏曲", "梨园春": "河南戏曲", "吉林综艺": "吉视综艺文化",
        "BRTVKAKU": "BRTV卡酷少儿", "kaku少儿": "BRTV卡酷少儿", "北京卡通": "BRTV卡酷少儿",
        "卡酷卡通": "BRTV卡酷少儿", "卡酷动画": "BRTV卡酷少儿", "佳佳动画": "嘉佳卡通",
        "CGTN今日世界": "CGTN", "CGTN英语": "CGTN", "ICS": "上视ICS外语频道",
        "法制天地": "法治天地", "都市时尚": "都市剧场", "上海炫动卡通": "哈哈炫动",
        "炫动卡通": "哈哈炫动", "旅游卫视": "海南卫视", "福建东南卫视": "东南卫视",
        "福建东南": "东南卫视", "南方卫视粤语节目9": "广东大湾区频道",
        "内蒙古蒙语卫视": "内蒙古蒙语频道", "南方卫视": "广东大湾区频道",
        "家庭影院": "CHC家庭影院", "动作电影": "CHC动作电影", "影迷电影": "CHC影迷电影",
        "中国教育1": "CETV1", "CETV1中教": "CETV1", "中国教育2": "CETV2",
        "中国教育4": "CETV4", "CCTVnews": "CGTN", "1资讯": "凤凰资讯台",
        "2中文": "凤凰台", "3XG": "香港台"
    }
    
    # 应用替换规则
    for old, new in cctv_mappings.items():
        name = name.replace(old, new)
    
    for old, new in other_mappings.items():
        name = name.replace(old, new)
    
    return name

async def fetch_live_interface(session, url, semaphore):
    """获取并处理live_interface.txt数据"""
    async with semaphore:
        try:
            async with session.get(url, timeout=CONFIG['timeout']) as response:
                content = await response.text()
                lines = content.strip().split('\n')
                
                # 提取基础URL部分
                url_parts = url.split('/')
                base_url = f"{url_parts[0]}//{url_parts[2]}"
                
                results = []
                for line in lines:
                    if 'udp' not in line and 'rtp' not in line:
                        line = line.strip()
                        if line and ',' in line:
                            name, channel_url = line.split(',', 1)
                            name = normalize_channel_name(name)
                            
                            # 处理相对URL
                            if not channel_url.startswith('http'):
                                channel_url = f"{base_url}/{channel_url.lstrip('/')}"
                            
                            results.append(f"{name},{channel_url}")
                
                return results
                
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return []

async def process_valid_urls(session, valid_urls, semaphore):
    """处理所有有效URL"""
    all_results = []
    tasks = [asyncio.create_task(fetch_live_interface(session, url, semaphore)) for url in valid_urls]
    results = await asyncio.gather(*tasks)
    
    for sublist in results:
        all_results.extend(sublist)
    
    return list(set(all_results))  # 去重

def test_channel_speed(channel_name, channel_url):
    """测试频道速度"""
    try:
        # 获取TS文件列表
        channel_url_t = channel_url.rstrip(channel_url.split('/')[-1])
        response = requests.get(channel_url, timeout=CONFIG['timeout'])
        lines = response.text.strip().split('\n')
        
        if not lines:
            return None
            
        ts_lists = [line.split('/')[-1] for line in lines if not line.startswith('#')]
        if not ts_lists:
            return None
        
        # 测试第一个TS文件速度
        ts_url = channel_url_t + ts_lists[0]
        
        start_time = time.time()
        content = requests.get(ts_url, timeout=CONFIG['timeout']).content
        end_time = time.time()
        
        if not content:
            return None
            
        # 计算速度
        response_time = end_time - start_time
        file_size = len(content)
        download_speed = file_size / response_time / 1024 / 1024  # MB/s
        
        # 应用速度限制
        normalized_speed = max(min(download_speed, CONFIG['max_speed']), CONFIG['min_speed'])
        
        # 清理临时文件
        ts_filename = ts_lists[0].split('.')[0] + '.ts'
        if os.path.exists(ts_filename):
            os.remove(ts_filename)
            
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
            
        # 计算并显示进度
        processed = len(results) + len(error_channels)
        progress = processed / all_results_count * 100
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{current_time} 可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{all_results_count} 个 , 总进度：{progress:.2f} %")
        
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
    
    # 保存带速度的完整结果
    with open(CONFIG['output_speed'], 'w', encoding='utf-8') as file:
        for name, url, speed in results:
            file.write(f"{name},{url},{speed}\n")
    
    # 保存分类频道列表
    now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=8)
    current_time = now.strftime("%Y/%m/%d %H:%M")
    
    with open(CONFIG['output_channels'], 'w', encoding='utf-8') as file:
        # 央视频道
        file.write(f'央视频道{current_time}更新,#genre#\n')
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
    # 读取原始URL文件
    urls_all = []
    with open(CONFIG['input_file'], 'r', encoding='utf-8') as file:
        for line in file:
            url = line.strip()
            if url:
                urls_all.append(f"http://{url}")
    
    # 预处理URL (IP第四位修改为1)
    x_urls = []
    for url in set(urls_all):  # 先对原始URL去重
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
    
    unique_urls = list(set(x_urls))  # 最终去重

    # 检查URL可访问性
    semaphore = asyncio.Semaphore(CONFIG['max_concurrent'])
    async with aiohttp.ClientSession() as session:
        print("开始扫描有效服务器...")
        valid_urls = await check_urls(session, unique_urls, semaphore)
        print(f"共发现 {len(valid_urls)} 个有效服务器")
        
        print("开始获取频道列表...")
        all_results = await process_valid_urls(session, valid_urls, semaphore)
        print(f"共获取 {len(all_results)} 个频道")
    
    # 多线程测试频道速度
    print("开始测试频道速度...")
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
        channel_name, channel_url = result.split(',', 1)
        task_queue.put((channel_name, channel_url))
    
    # 等待所有任务完成
    task_queue.join()
    
    # 保存结果
    print("正在保存结果...")
    save_results(results)
    print(f"结果已保存到 {CONFIG['output_speed']} 和 {CONFIG['output_channels']}")

if __name__ == "__main__":
    asyncio.run(main())