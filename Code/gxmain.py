import eventlet
eventlet.monkey_patch()

import time
import datetime
import threading
import os
import re
import concurrent.futures
from queue import Queue
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import requests
from collections import defaultdict

# 全局配置
CONFIG = {
    'timeout': 1.5,  # 基本超时时间
    'max_workers': 15,  # 工作线程数
    'result_counter': 8,  # 每个频道最大保留结果数
    'min_speed': 0.001,  # 最低速度限制(MB/s)
    'max_speed': 100,    # 最高速度限制(MB/s)
}

def modify_urls(url):
    modified_urls = []
    ip_start_index = url.find("//") + 2
    ip_end_index = url.find(":", ip_start_index)
    base_url = url[:ip_start_index]  # http:// or https://
    ip_address = url[ip_start_index:ip_end_index]
    port = url[ip_end_index:]
    ip_end = "/ZHGXTV/Public/json/live_interface.txt"
    for i in range(1, 256):
        modified_ip = f"{ip_address[:-1]}{i}"
        modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
        modified_urls.append(modified_url)
    return modified_urls

def is_url_accessible(url):
    try:
        response = requests.get(url, timeout=1.5)
        if response.status_code == 200:
            return url
    except requests.exceptions.RequestException:
        pass
    return None

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
        print(f"{current_time} 可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{all_results_count} 个 ,总进度：{progress:.2f} %。")
        
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
    
    # 保存分类频道列表
    with open("txt/gxtv.txt", 'w', encoding='utf-8') as file:
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

def main():
    results = []
    urls_all = []
    with open('data/jdgx.ip', 'r', encoding='utf-8') as file:
        lines = file.readlines()
        for line in lines:
            url = line.strip()
            url = f"http://{url}"
            urls_all.append(url)
            
        urls = set(urls_all)  # 去重得到唯一的URL列表
        x_urls = []
        for url in urls:  # 对urls进行处理，ip第四位修改为1，并去重
            url = url.strip()
            ip_start_index = url.find("//") + 2
            ip_end_index = url.find(":", ip_start_index)
            ip_dot_start = url.find(".") + 1
            ip_dot_second = url.find(".", ip_dot_start) + 1
            ip_dot_three = url.find(".", ip_dot_second) + 1
            base_url = url[:ip_start_index]  # http:// or https://
            ip_address = url[ip_start_index:ip_dot_three]
            port = url[ip_end_index:]
            ip_end = "1"
            modified_ip = f"{ip_address}{ip_end}"
            x_url = f"{base_url}{modified_ip}{port}\n"
            x_urls.append(x_url)    
        urls = sorted(set(x_urls))  # 去重得到唯一的URL列表

        valid_urls = []
        # 多线程获取可用url
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            futures = []
            for url in urls:
                url = url.strip()
                modified_urls = modify_urls(url)
                for modified_url in modified_urls:
                    futures.append(executor.submit(is_url_accessible, modified_url))
    
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    valid_urls.append(result)
                    print(result)
            valid_urls = sorted(set(valid_urls))      
        
        # 遍历网址列表，获取JSON文件并解析
        all_results = []
        for url in valid_urls:
            try:
                # 发送GET请求获取JSON文件，设置超时时间为0.5秒
                json_url = f"{url}"
                response = requests.get(json_url, timeout=2)
                json_data = response.content.decode('utf-8')
                try:
                    # 按行分割数据
                    lines = json_data.split('\n')
                    for line in lines:
                        if 'udp' not in line and 'rtp' not in line:
                            line = line.strip()
                            if line:
                                name, channel_url = line.split(',')
                                urls = channel_url.split('/', 3)
                                url_data = json_url.split('/', 3)
                                if len(urls) >= 4:
                                    urld = (f"{urls[0]}//{url_data[2]}/{urls[3]}")
                                else:
                                    urld = (f"{urls[0]}//{url_data[2]}")
                                
                                if name and urld:
                                    # 删除特定文字
                                    name = name.replace("cctv", "CCTV")
                                    name = name.replace("中央", "CCTV")
                                    name = name.replace("央视", "CCTV")
                                    name = name.replace("高清", "")
                                    name = name.replace("超清", "")
                                    name = name.replace("超高", "")
                                    name = name.replace("HD", "")
                                    name = name.replace("标清", "")
                                    name = name.replace("频道", "")
                                    name = name.replace("-", "")
                                    name = name.replace(" ", "")
                                    name = name.replace("PLUS", "+")
                                    name = name.replace("＋", "+")
                                    name = name.replace("(", "")
                                    name = name.replace(")", "")
                                    name = re.sub(r"CCTV(\d+)台", r"CCTV\1", name)
                                    name = name.replace("CCTV1综合", "CCTV1")
                                    name = name.replace("CCTV2财经", "CCTV2")
                                    name = name.replace("CCTV3综艺", "CCTV3")
                                    name = name.replace("CCTV4国际", "CCTV4")
                                    name = name.replace("CCTV4广电", "CCTV4")
                                    name = name.replace("CCTV4中文国际", "CCTV4")
                                    name = name.replace("CCTV4欧洲", "CCTV4")
                                    name = name.replace("CCTV5体育", "CCTV5")
                                    name = name.replace("CCTV6电影", "CCTV6")
                                    name = name.replace("CCTV7军事", "CCTV7")
                                    name = name.replace("CCTV7军农", "CCTV7")
                                    name = name.replace("CCTV7农业", "CCTV7")
                                    name = name.replace("军农", "")
                                    name = name.replace("CCTV7国防军事", "CCTV7")
                                    name = name.replace("CCTV8电视剧", "CCTV8")
                                    name = name.replace("CCTV9记录", "CCTV9")
                                    name = name.replace("CCTV9纪录", "CCTV9")
                                    name = name.replace("CCTV10科教", "CCTV10")
                                    name = name.replace("CCTV11戏曲", "CCTV11")
                                    name = name.replace("CCTV12社会与法", "CCTV12")
                                    name = name.replace("CCTV13新闻", "CCTV13")
                                    name = name.replace("CCTV新闻", "CCTV13")
                                    name = name.replace("CCTV14少儿", "CCTV14")
                                    name = name.replace("CCTV少儿", "CCTV14")
                                    name = name.replace("CCTV15音乐", "CCTV15")
                                    name = name.replace("CCTV16奥林匹克", "CCTV16")
                                    name = name.replace("CCTV17农业农村", "CCTV17")
                                    name = name.replace("CCTV17农业", "CCTV17")
                                    name = name.replace("CCTV17军农", "CCTV17")
                                    name = name.replace("CCTV17军事", "CCTV17")
                                    name = name.replace("CCTV5+体育赛视", "CCTV5+")
                                    name = name.replace("CCTV5+体育赛事", "CCTV5+")
                                    name = name.replace("CCTV5+体育", "CCTV5+")
                                    name = name.replace("CCTV足球", "CCTV风云足球")
                                    name = name.replace("上海卫视", "东方卫视")
                                    name = name.replace("奥运匹克", "")
                                    name = name.replace("军农", "")
                                    name = name.replace("回放", "")
                                    name = name.replace("测试", "")
                                    name = name.replace("CCTV5卡", "CCTV5")
                                    name = name.replace("CCTV5赛事", "CCTV5")
                                    name = name.replace("CCTV教育", "CETV1")
                                    name = name.replace("中国教育1", "CETV1")
                                    name = name.replace("CETV1中教", "CETV1")
                                    name = name.replace("中国教育2", "CETV2")
                                    name = name.replace("中国教育4", "CETV4")
                                    name = name.replace("CCTV5+体育赛视", "CCTV5+")
                                    name = name.replace("CCTV5+体育赛事", "CCTV5+")
                                    name = name.replace("CCTV5+体育", "CCTV5+")
                                    name = name.replace("CCTV赛事", "CCTV5+")
                                    name = name.replace("CCTV教育", "CETV1")
                                    name = name.replace("CCTVnews", "CGTN")
                                    name = name.replace("1资讯", "凤凰资讯台")
                                    name = name.replace("2中文", "凤凰台")
                                    name = name.replace("3XG", "香港台")
                                    name = name.replace("上海卫视", "东方卫视")
                                    name = name.replace("全纪实", "乐游纪实")
                                    name = name.replace("金鹰动画", "金鹰卡通")
                                    name = name.replace("河南新农村", "河南乡村")
                                    name = name.replace("河南法制", "河南法治")
                                    name = name.replace("文物宝库", "河南收藏天下")
                                    name = name.replace("梨园", "河南戏曲")
                                    name = name.replace("梨园春", "河南戏曲")
                                    name = name.replace("吉林综艺", "吉视综艺文化")
                                    name = name.replace("BRTVKAKU", "BRTV卡酷少儿")
                                    name = name.replace("kaku少儿", "BRTV卡酷少儿")
                                    name = name.replace("纪实科教", "BRTV纪实科教")
                                    name = name.replace("北京卡通", "BRTV卡酷少儿")
                                    name = name.replace("卡酷卡通", "BRTV卡酷少儿")
                                    name = name.replace("卡酷动画", "BRTV卡酷少儿")
                                    name = name.replace("佳佳动画", "嘉佳卡通")
                                    name = name.replace("CGTN今日世界", "CGTN")
                                    name = name.replace("CGTN英语", "CGTN")
                                    name = name.replace("ICS", "上视ICS外语频道")
                                    name = name.replace("法制天地", "法治天地")
                                    name = name.replace("都市时尚", "都市剧场")
                                    name = name.replace("上海炫动卡通", "哈哈炫动")
                                    name = name.replace("炫动卡通", "哈哈炫动")
                                    name = name.replace("经济科教", "TVB星河")
                                    name = name.replace("回放", "")
                                    name = name.replace("测试", "")
                                    name = name.replace("旅游卫视", "海南卫视")
                                    name = name.replace("福建东南卫视", "东南卫视")
                                    name = name.replace("福建东南", "东南卫视")
                                    name = name.replace("南方卫视粤语节目9", "广东大湾区频道")
                                    name = name.replace("内蒙古蒙语卫视", "内蒙古蒙语频道")
                                    name = name.replace("南方卫视", "广东大湾区频道")
                                    name = name.replace("中国教育1", "CETV1")
                                    name = name.replace("南方1", "广东经济科教")
                                    name = name.replace("南方4", "广东影视频道")
                                    name = name.replace("吉林市1", "吉林新闻综合")
                                    name = name.replace("家庭影院", "CHC家庭影院")
                                    name = name.replace("动作电影", "CHC动作电影")
                                    name = name.replace("影迷电影", "CHC影迷电影")
                                    all_results.append(f"{name},{urld}")
                except:
                    continue
            except:
                continue

        # 去重得到唯一的URL列表
        all_results = sorted(set(all_results))

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
    main()