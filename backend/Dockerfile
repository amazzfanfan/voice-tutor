# 本地或通用 CI 环境的 Docker 构建文件
FROM  m.daocloud.io/docker.io/library/python:3.11.5
#FROM rag-editor:1.2.0

#定义时区参数
ENV TZ=Asia/Shanghai
#设置时区
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo '$TZ' > /etc/timezone
#设置编码
ENV LANG=C.UTF-8
ENV PYTHONUNBUFFERED=1
# 添加 Python 路径


# 创建工程目录
RUN mkdir -p /home/app/src/
# 复制整个 src 目录
COPY ./src /home/app/src/
# 确保 algo 目录被复制（使用测试中有效的方法）
COPY ./build.sh /home/app/
COPY ./entrypoint.sh /home/app/
COPY ./requirements.txt /home/app/
COPY ./packages.txt /home/app/
COPY ./run_web_api.py /home/app/
COPY resources/Sofiles/libGL.so.1 /usr/lib/x86_64-linux-gnu/
COPY resources/Sofiles/libGLdispatch.so.0 /usr/lib/x86_64-linux-gnu/
COPY resources/Sofiles/libGLX.so.0 /usr/lib/x86_64-linux-gnu/
COPY resources/Sofiles/libGLX_mesa.so.0 /usr/lib/x86_64-linux-gnu/

# 设置工作路径

WORKDIR /home/app
RUN cd /home/app

# apt换源
RUN  sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources
RUN apt-get clean
RUN apt-get update

# 将win文件转化成linux文件 防止sh运行错误
RUN apt-get install -y dos2unix*
RUN find -type f | xargs dos2unix -o
RUN apt-get install --no-install-recommends -y < /home/app/packages.txt \
    && apt-get install -y fonts-noto-cjk fonts-noto-core fontconfig \
    && rm -rf /var/lib/apt/lists/*


# pip换源、安装库
RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
RUN pip config set install.trusted-host mirrors.tuna.tsinghua.edu.cn
RUN pip install -r requirements.txt
RUN pip install gunicorn
RUN pip install nuitka


# 编译文件
RUN ls -lh /home/app/src/algo
RUN /bin/bash /home/app/build.sh
RUN ls -lh /home/app/src


# 加运行权限
RUN chmod +x entrypoint.sh

# 线上模式 将运行的命令写到脚本entrypoint.sh中
CMD ["/bin/bash", "-c", "/home/app/entrypoint.sh"]
