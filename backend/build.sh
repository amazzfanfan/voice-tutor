#!/bin/bash
# 如果打包时这里报错，可能是因为行分隔符不是是CRLF，改成LF即可

# 目录获取
work_dir="$(cd $(dirname \$0) && pwd)"
# 源代码目录
src_dir="${work_dir}/src"
# 算法代码目录
algo_dir="${src_dir}/algo"
# 构建目录
build_dir="${src_dir}/build"

## 加密
cd "$src_dir"
if [ -d "$algo_dir" ]; then
     echo "Algo code directory exists, starting encryption..."
     # 加密编译
     python3 -m nuitka --module algo --include-package=algo --output-dir=${build_dir}
     echo "Compile finished"
     # 移动.so文件
     cp ${build_dir}/*.so ${src_dir}
     # # 删除 algo 目录
     rm -rf ${algo_dir}
     rm -rf ${build_dir}
     echo "Algo code has been deleted and the encryption has been completed."
else
     echo "Algo code directory does not exist, please check."
fi
