#!/bin/bash
# 如果打包时这里报错，可能是因为行分隔符不是是CRLF，改成LF即可
export LANG="en_US.UTF-8"

if [[ "$1" == "bash" || "$1" == "sh" ]]; then
   bash
else
   # 获取当前目录
   work_dir="$(cd $(dirname \$0) && pwd)"
   # 源代码目录
   src_dir="${work_dir}/src"
   # gunicorn 配置文件
   gunicorn_conf_file="${src_dir}/conf/gunicorn.py"
   ## 启动服务
   cd "$work_dir"
   export PYTHONPATH="${src_dir}:${PYTHONPATH}"
   # 检查是否有正在运行的 gunicorn 任务
   result=$(ps -ef | grep gunicorn | grep -v grep | awk '{print $2}')
   if [ -n "$result" ]; then
      echo "Killing existing gunicorn processes..."
      # 杀掉所有 gunicorn 进程
      kill -9 $result
      echo "Existing gunicorn processes killed."
   fi
   # 启动新的 gunicorn 任务
   echo "Starting new gunicorn process..."
   gunicorn algo.web_api:project_app -c ${gunicorn_conf_file}
   echo "New online_task started."

fi




