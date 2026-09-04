# -*- coding: utf-8 -*-
# cython: language_level=3
"""
算法接口通用工具函数，有配置文件读写，日志工具封装
"""
import os
import logging
import time
import json
from configparser import ConfigParser
from logging.handlers import TimedRotatingFileHandler
import platform
import inspect

if platform.system() == 'Linux':
    import fcntl

'''当前文件才定义日志类，因此本文件只能使用基础日志'''
for logger_name in [
    "uvicorn.access",
    "gunicorn.access", 
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "starlette",
    "fastapi"
]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)
logger = logging.getLogger('tools')
logger.setLevel(logging.INFO)
console = logging.StreamHandler()
logger.addHandler(console)

'''
自动获取src下文件夹的真实目录
SRC_ALGO_DIR : project/src/algo
SRC_CONF_DIR : project/src/conf
SRC_DATA_DIR : project/src/data
SRC_MODEL_DIR : project/src/model
'''


def get_code_real_path():
    """
    获取project/src/algo的真实目录，tools文件应当在其子目录下且最多10层
    """
    # 当前文件所在目录
    cur_dir_path = os.path.normpath(os.path.dirname(os.path.realpath(__file__)))
    for i in range(0, 10):
        temp_dir_name = os.path.basename(cur_dir_path)
        if temp_dir_name == 'algo':
            break
        else:
            # 往上级目录走
            cur_dir_path = os.path.normpath(os.path.join(cur_dir_path, '..'))
            if i == 10:
                raise RuntimeError("web_tools.py 没有在algo的子目录下")
    return cur_dir_path


SRC_ALGO_DIR = get_code_real_path()
logger.info("SRC_ALGO_DIR is %s", SRC_ALGO_DIR)
SRC_CONF_DIR = os.path.normpath(os.path.join(SRC_ALGO_DIR, '../conf'))
DEPLOY_CONF_DIR = os.path.normpath(os.path.join(SRC_ALGO_DIR, '../../conf'))
SRC_DATA_DIR = os.path.normpath(os.path.join(SRC_ALGO_DIR, '../data'))
SRC_MODEL_DIR = os.path.normpath(os.path.join(SRC_ALGO_DIR, '../model'))
PRO_BASE_DIR = os.path.normpath(os.path.join(SRC_ALGO_DIR, '../../'))
'''日志文件保存类'''


class MultiCompatibleTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    为了支持多线程和多进程日志重构的类，该类实现了多线程和多进程安全，也可以滚动日志保存（即指定数量、指定时间内日志文件的保存）
    该类同时支持终端日志收集，部署平台可以统一采集日志。
    """

    def do_rollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        # get the time that this sequence started at and make it a TimeTuple
        current_time = int(time.time())
        dst_now = time.localtime(current_time)[-1]
        t = self.rolloverAt - self.interval
        if self.utc:
            time_tuple = time.gmtime(t)
        else:
            time_tuple = time.localtime(t)
            dst_then = time_tuple[-1]
            if dst_now != dst_then:
                if dst_now:
                    addend = 3600
                else:
                    addend = -3600
                time_tuple = time.localtime(t + addend)
        dfn = time.strftime(self.suffix, time_tuple) + "_" + self.baseFilename
        # 兼容多进程并发 LOG_ROTATE
        if not os.path.exists(dfn):
            f = open(self.baseFilename, 'a')
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            if os.path.exists(self.baseFilename):
                os.rename(self.baseFilename, dfn)
        if self.backupCount > 0:
            for s in self.getFilesToDelete():
                os.remove(s)
        if not self.delay:
            self.stream = self._open()
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at = new_rollover_at + self.interval
        # If DST changes and midnight or weekly rollover, adjust for this.
        if (self.when == 'MIDNIGHT' or self.when.startswith('W')) and not self.utc:
            dst_at_rollover = time.localtime(new_rollover_at)[-1]
            if dst_now != dst_at_rollover:
                if not dst_now:  # DST kicks in before next rollover, so we need to deduct an hour
                    addend = -3600
                else:  # DST bows out before next rollover, so we need to add an hour
                    addend = 3600
                new_rollover_at += addend
        self.rolloverAt = new_rollover_at


''' 日志工具类'''


class MyLogger(object):
    """
    日志工具类,支持多线程的日志工具类，可以把不同级别的日志输出到不同的日志文件中，初始化时如果不指定参数，将使用配置文件中的配置
    属性：
    log_name: 日志类的名字，日志文件以此作为前缀名字
    when: 日志滚动保存时的时间单位
    interval: 日志滚动保存时的时间间隔
    backup_count: 日志滚动保存时的同一类型日志保留的数量
    output_level: 日志的输出等级
    log_dir_name: 日志文件自定义目录名
    formatter: 日志的输出格式
    log_dir： 日志存放的实际目录，放在日志根目录“项目/src/logs/”下面
    __loggers：日志关键属性包含handler等
    """

    def __init__(self, log_name=None, when=None, interval: int = None, backup_count: int = None,
                 output_level=None, formatter=None, is_new_file=False):

        """
        :param log_name: 日志类的名字，日志文件以此作为前缀名字
        :param when: 日志滚动保存时的时间单位
        :param interval: 日志滚动保存时的时间间隔
        :param backup_count: 日志滚动保存时的同一类型日志保留的数量
        :param output_level: 日志的输出等级
        :param formatter: 日志的输出格式
        :param is_new_file: 是否以日志名创建新的日志文件
        :return: 内部初始化函数无返回
        """
        # 获取配置文件的参数并初始化属性
        self.__init_from_conf()
        # 手动设置参数时重新设置属性
        self.__set_attribute(log_name=log_name, when=when, interval=interval, backup_count=backup_count,
                             output_level=output_level, formatter=formatter, is_new_file=is_new_file)
        # 初始化日志文件目录
        self.__init_logs_dir()
        # 日志类的关键信息包含handler等

        self.__loggers = {}
        # 正式创建日志的输出流
        self.create_handlers()

    def __init_logs_dir(self):
        """
        初始化日志文件的的存放目录，包裹更新日志文件的实际存放地址，创建日志文件夹
        :return: 内部初始化函数无返回
        """
        self.logs_root_dir = os.path.normpath(os.path.join(PRO_BASE_DIR, 'src/logs/'))
        self.log_dir = self.logs_root_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

    def __init_from_conf(self):
        """
        从配置文件读取日志默认配置参数，如果指定了配置则使用指定配置
        :return: 内部初始化函数无返回
        """
        # 读取日志配置文件中日志类的默认参数
        my_config_parser = MyConfigParser(include_file_list=['logger.ini'])
        log_name = my_config_parser.get(section='logger', option='log_name')
        when = my_config_parser.get(section='logger', option='when')
        interval = my_config_parser.getint(section='logger', option='interval')
        backup_count = my_config_parser.getint(section='logger', option='backup_count')
        output_level = my_config_parser.get(section='logger', option='output_level')
        formatter = my_config_parser.get(section='logger', option='formatter', raw=True)
        self.log_name = log_name
        self.when = when
        self.interval = interval
        self.backup_count = backup_count
        self.output_level = output_level
        self.formatter = formatter

    def __set_attribute(self, log_name=None, when=None, interval=None, backup_count=None,
                        output_level=None, formatter=None, is_new_file=False):

        if log_name is not None and isinstance(log_name, str):
            self.log_name = log_name
        if when is not None and isinstance(when, str):
            self.when = when
        if self.interval is not None and isinstance(interval, int):
            self.interval = interval
        if self.backup_count is not None and isinstance(backup_count, int):
            self.backup_count = backup_count
        if output_level is not None and isinstance(output_level, str):
            self.output_level = output_level
        if formatter is not None and isinstance(formatter, str):
            self.formatter = formatter
        if is_new_file is not None and isinstance(is_new_file, bool):
            self.is_new_file = is_new_file

    def append_file_message(self, *message):
        """重写日志类后无法按照原始方式输出调用文件和代码行数，因此需要修改一下输入信息"""
        file_information = "module - line :"
        if len(inspect.stack()) >= 3:
            frame, filename, lineNo, functionName, code, unknowField = inspect.stack()[2]
            call_file_name = os.path.basename(filename)
            call_code_line = lineNo
            # print(str(message[0]))
            file_information = "{} - {} : ".format(call_file_name, call_code_line)
        # print(file_information)
        if len(message) == 0:
            message = (file_information,)
            return message
        else:
            details = [file_information + str(message[0])]
            for i in range(1, len(message)):
                details.append(message[i])
        message = tuple(details)
        return message

    def info(self, *message):
        """info 类日志"""
        message = self.append_file_message(*message)
        self.__loggers[self.log_name + '.INFO'].info(*message)

    def error(self, *message):
        """error 类日志"""
        message = self.append_file_message(*message)
        self.__loggers[self.log_name + '.ERROR'].error(*message)

    def warning(self, *message):
        """warning 类日志"""
        message = self.append_file_message(*message)
        self.__loggers[self.log_name + '.WARNING'].warning(*message)

    def debug(self, *message):
        """debug 类日志"""
        message = self.append_file_message(*message)
        self.__loggers[self.log_name + '.DEBUG'].debug(*message)

    def critical(self, *message):
        """critical 类日志"""
        # message = self.get_log_message("critical", message)
        self.__loggers[self.log_name + '.CRITICAL'].critical(*message)

    def create_handlers(self):
        log_dir, log_name = self.log_dir, self.log_name
        when, interval, backup_count = self.when, self.interval, self.backup_count
        output_level, formatter_str = self.output_level, self.formatter
        # 创建一个handler，用于将日志输出到控制台
        output_logging_level = None
        ch = logging.StreamHandler()
        if output_level == "NOTSET":
            ch.setLevel(logging.NOTSET)
            output_logging_level = logging.NOTSET
        elif output_level == "DEBUG":
            ch.setLevel(logging.DEBUG)
            output_logging_level = logging.DEBUG
        elif output_level == "INFO":
            ch.setLevel(logging.INFO)
            output_logging_level = logging.INFO
        elif output_level == "WARNING":
            ch.setLevel(logging.WARNING)
            output_logging_level = logging.WARNING
        elif output_level == "ERROR":
            ch.setLevel(logging.ERROR)
            output_logging_level = logging.ERROR
        elif output_level == "CRITICAL":
            ch.setLevel(logging.CRITICAL)
            output_logging_level = logging.CRITICAL
        else:
            # 默认输出INFO及以上日志等级
            ch.setLevel(logging.INFO)
            output_logging_level = logging.INFO

        handlers = {self.log_name + '.NOTSET': log_name + "-notset.log",
                    self.log_name + '.DEBUG': log_name + "-debug.log",
                    self.log_name + '.INFO': log_name + "-info.log",
                    self.log_name + '.WARNING': log_name + "-warning.log",
                    self.log_name + '.ERROR': log_name + "-error.log",
                    self.log_name + '.CRITICAL': log_name + "-critical.log"}
        formatter = logging.Formatter(formatter_str)
        ch.setFormatter(formatter)
        for haner_name in list(handlers.keys()):
            t_logger = logging.getLogger(haner_name)
            # 是否根据日志名创建日志文件件，否的话日志写在一个文件里面
            if self.is_new_file is True:
                file_haner_name = handlers[haner_name]
            else:
                file_haner_name = 'default-' + handlers[haner_name].split('-')[-1]
            if platform.system() == 'Linux':
                # 多线程多进程日志 Linux下才能使用
                file_handler = MultiCompatibleTimedRotatingFileHandler(
                    filename=os.path.join(log_dir, file_haner_name),
                    when=when, interval=interval,
                    backupCount=backup_count, delay=True,
                    encoding='utf-8')
            else:
                # 不支持多线程日志,windods测试环境使用
                file_handler = TimedRotatingFileHandler(filename=os.path.join(log_dir, file_haner_name),
                                                        when=when, interval=interval,
                                                        backupCount=backup_count, delay=True,
                                                        encoding='utf-8')
            file_handler.setFormatter(formatter)
            t_logger.setLevel(output_logging_level)
            if not t_logger.hasHandlers():
                t_logger.addHandler(file_handler)  # 输出到文件的handler
                t_logger.addHandler(ch)  # 输出到控制台的handler
                t_logger.propagate = False
            self.__loggers.update({haner_name: t_logger})
        self.info("The new logger initialization is complete")


'''配置文件读写类'''


class MyConfigParser(ConfigParser):
    """
     该类继承了python原生配置读写类，封装了配置文件读写顺序，位置，其余函数通用。
     配置读写工具类,只需要指明要读取的文件名列表和排除在外的文件名列表，会按照指定优先级读取配置文件
     第1步：读取“project/src/conf/” 目录的配置文件中的参数值
     第2步：读取“project/conf/” 目录的配置文件 覆盖第1步读取的值
     第3步：读取系统环境变量中配置文件，系统变量名称全部大写，覆盖前2步读取的值
     格式：ALGO__SECTION__OPTION，（2个下划线）它的值对应配置文件中的section和option的参数。
            用于在镜像启动时指定配置
    """
    SYSTEM_VARIABLE_PREFIX = 'ALGO__'

    def __init__(self, include_file_list=None, exclude_file_list=None):
        ConfigParser.__init__(self)
        # 指定读取某些文件名的列表
        self.include_file_list = include_file_list
        # 指定不被读取的配置文件名列表
        default_exclude_file_list = ['gunicorn.ini', 'gunicorn.py']
        if exclude_file_list is None:
            self.exclude_file_list = default_exclude_file_list
        else:
            default_exclude_file_list.extend(exclude_file_list)
            self.exclude_file_list = default_exclude_file_list
        # 读取某个配置文件
        self.__conf_file_read()
        # 读取到的属性是否存在环境变量，使用环境变量的值替换
        self.__system_env_read()

    def __conf_file_read(self):
        """
        读取配置文件夹路径下的所有配置文件（排除exclude_file_list列表中的文件）
        :return: 内部初始化函数无返回
        """

        # 先读取"project/src/conf/"目录下的配置文件
        if os.path.exists(SRC_CONF_DIR):
            if self.include_file_list is None:
                files = os.listdir(SRC_CONF_DIR)
            else:
                files = self.include_file_list
            ini_suffix = ['.ini']
            for filename in files:
                file_path = os.path.join(SRC_CONF_DIR, filename)
                if os.path.isfile(file_path):
                    suffix = os.path.splitext(filename)[-1]
                    if (suffix in ini_suffix) and (filename not in self.exclude_file_list):
                        if platform.system() == 'Linux':
                            with open(file_path, 'r') as f:
                                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                                self.read(file_path, encoding='utf-8')
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        else:
                            self.read(file_path, encoding='utf-8')

        # 再读取部署环境提供的外部配置，用于覆盖默认配置。
        if os.path.exists(DEPLOY_CONF_DIR):
            if self.include_file_list is None:
                files = os.listdir(DEPLOY_CONF_DIR)
            else:
                files = self.include_file_list
            ini_suffix = ['.ini']
            for file in files:
                file_path = os.path.join(DEPLOY_CONF_DIR, file)
                if os.path.isfile(file_path):
                    suffix = os.path.splitext(file)[-1]
                    if (suffix in ini_suffix) and (file not in self.exclude_file_list):
                        if platform.system() == 'Linux':
                            with open(file_path, 'r') as f:
                                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                                self.read(file_path, encoding='utf-8')
                                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                        else:
                            self.read(file_path, encoding='utf-8')

    def get_all_attribute_name(self):
        """
        获取配置中的所有属性名称
        :return: 返回数据类型为字典，res_dic={section:[option1,option2.....]}   section:str，option:str，
        """
        res_dic = {}
        sections = self.sections()
        for section_name in sections:
            options = self.options(section=section_name)
            temp_dic = {section_name: options}
            res_dic.update(temp_dic)
        return res_dic

    def __system_env_read(self):
        """
        如果读取到的配置属性存在环境变量，那么使用环境变量的数据替代工具类中存放的数据
        :return:
        """
        attribute_name_dic = self.get_all_attribute_name()
        for section_name in attribute_name_dic:
            options = attribute_name_dic[section_name]
            for option_name in options:
                system_variable_name = self.SYSTEM_VARIABLE_PREFIX + section_name + '__' + option_name
                system_variable_name = system_variable_name.upper()
                system_variable_value = os.getenv(system_variable_name)
                if system_variable_value is not None:
                    self.set(section=section_name, option=option_name, value=system_variable_value)

    def update_content(self):
        """
        使用update_content函数可以重新读取配置参数，顺序与上面一致，读操作已经多进程加锁。
        写操作请新建一个空白基类ConfigParser，添加属性后写如文件，示例代码放最后，自定义保存文件的位置和名字，该操作不推荐。
        '''
        # 创建一个空白的ConfigParser类，并添加属性
        blank_config = ConfigParser()
        # 读取一个配置文件后再修改属性 blank_config
        blank_config.add_section("test-section1") # 添加属性之前要添加section
        blank_config.set(section="test-section1", option="test-option1", value="test-value1")
        blank_config.set(section="test-section1", option="test-option2", value="test-value2")
        # 设置写入的文件路径，并使用覆盖写
        filename = "test.ini"
        with open(os.path.join(SRC_CONF_DIR, filename), 'w+', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            blank_config.write(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        '''
        """
        self.__conf_file_read()
        self.__system_env_read()

    def getjson(self, section, option):
        """
        读取json格式的配置参数，配置文件中直接读取字符串，如果有换行则会出现\n,所以需要转换。
        :param section:配置的section名字
        :param option: 配置的option名字
        :return: json
        """

        string = self.get(section=section, option=option, raw=True)
        result_json = json.loads(string)
        return result_json

    def getlist(self, section, option):
        """
        读取列表格式的配置参数
        :param section:配置的section名字
        :param option:配置的option名字
        :return:list
        """
        string = self.get(section=section, option=option, raw=True)
        result_list = json.loads(string)
        return result_list


"""
swagger静态资源挂载，防止无外网或跨域情况下无法访问
"""
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from starlette.staticfiles import StaticFiles
from fastapi import FastAPI


def register_static(app: FastAPI):
    # 1. 挂载本地静态文件目录
    app.mount("/static", StaticFiles(directory="resources/swagger-static"), name="static")

    # 2. 自定义 Swagger UI 路由
    @app.get("/docs", include_in_schema=False)
    async def get_swagger_ui():
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,  # 使用默认 /openapi.json 路径
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",  # 注意前导斜杠 /
            swagger_css_url="/static/swagger-ui/swagger-ui.css",       # 注意前导斜杠 /
            swagger_favicon_url="/static/swagger-ui/favicon.png",      # 注意前导斜杠 /
        )

    # 3. OAuth2 重定向路由（如果启用了认证）
    if app.swagger_ui_oauth2_redirect_url:
        @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
        async def swagger_ui_redirect():
            return get_swagger_ui_oauth2_redirect_html()

    # 4. 自定义 ReDoc 路由
    @app.get("/redoc", include_in_schema=False)
    async def get_redoc_ui():
        return get_redoc_html(
            openapi_url=app.openapi_url,  # 使用默认 /openapi.json 路径
            title=app.title + " - ReDoc",
            redoc_js_url="/static/redoc/redoc.standalone.js",  # 注意前导斜杠 /
            redoc_favicon_url="/static/redoc/favicon.png",     # 注意前导斜杠 /
            with_google_fonts=False,
        )
