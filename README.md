可以改检测超时时间60秒：res = requests.get(url, headers=headers, timeout=60)

可改每天拉取时间比如12小时：

 2. 定时自动触发（每天 UTC 时间 0点和12点，即北京时间早上 8点和晚上 20点）
  schedule:
    - cron: '0 0,12 * * *'


机器人添加变量：
1 TG的ID
TG_CHAT_1     TG_CHAT_2 

2 TG的token

TG_TOKEN_1   TG_TOKEN_2
