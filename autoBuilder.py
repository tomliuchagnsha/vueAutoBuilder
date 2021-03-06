#/usr/bin/env python
# -*- coding: utf8 -*-
   
import pysvn
import locale
import os
import shutil
import json
from config import *
import subprocess
import sys
import time,json,urllib2
from datetime import datetime
import requests

def get_login(realm, username, may_save):
    return True, Config.username, Config.password, True

def get_local_version(project):
    entry = client.info(project.get_local_code_path());
    return entry.commit_revision.number;

def get_remote_need_build_version(project,current_version):
    #只获取提交日志中包含 “#build#” 关键字的版本号，该关键字表示该版本需要进行build
    keyword = '#build#'; 
    revision = pysvn.Revision(pysvn.opt_revision_kind.number,current_version);
    log_list = client.log(project.get_svn_path(),revision_end = revision);
    validRevision = current_version;
    lastAuthor = '';
    
    for log in log_list:
        log_revision = log.revision.number;
        if keyword in log.message and log_revision >= validRevision:
            print_log('check buildable version:' + str(log_revision) + ',log:' + log.message);
            validRevision = log_revision;
            lastAuthor = log.author;
    return validRevision,lastAuthor;

def svn_update(project,target_version):
    try:
        code_path = project.get_local_code_path();
        client.cleanup(code_path);
        client.revert(code_path,True);
        revision = pysvn.Revision(pysvn.opt_revision_kind.number,target_version);
        client.update(code_path,revision = revision);
        print_log('update ' + project.get_name() + ' successfully');
    except Exception,err:
        print_log('update ' + project.get_name() + ' error:' + str(err));


def print_log(msg):
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime());
    try:
        if not os.path.exists(Config.log_dir):
            os.makedirs(Config.log_dir);

        #以下部分主要判断当前日志文件是否已过期(即已是新的一天)
        log_file = Config.log_dir + 'log.txt';
        if(os.path.exists(log_file)):
            last_modified_time = time.localtime(os.stat(log_file).st_mtime);
            last_modified_date = time.strftime('%d', last_modified_time);
            now_date = time.strftime('%d', time.localtime()) ;
            if(now_date != last_modified_date):#最后修改文件的日期与当前不一致时，将原日志文件进行转移，保证当前日志文件只包含当天的日志
                now_date_text = time.strftime('%Y-%m-%d', time.localtime());
                new_file_path = Config.log_dir + now_date_text + '-log.txt';
                os.rename(log_file,new_file_path);
  
        #记录日志
        fo = open(log_file, 'a');
        fo.write(now + ' ' + str(msg) + '\n');
        fo.close();
    except Exception,err:
        print now,'write log file error:' + str(err);
    
    print now,msg;

def check_need_update(project):
    current_version = get_local_version(project);
    latest_version,last_author = get_remote_need_build_version(project,current_version);#仅查询svn上需要build的最新版本号,防止无效获取并build
    return latest_version > current_version,latest_version,last_author;

def check_out(project):
    ret = client.checkout(project.get_svn_path(), project.get_local_code_path());

def ensure_checkout():
    for project in Config.projects:
        project_name = project.get_name();
        local_code_dir = project.get_local_code_path();
        exist = os.path.exists(local_code_dir);#判断是否存在该目录，因为如果存在目录则说明已经成功检出过
        if not exist:
            try:
                print_log('check out ' + project_name + ' start');
                check_out(project);
                print_log('check out ' + project_name + ' successfully');
            except Exception,err:
                print_log('check out ' + project_name + ' failed:' + str(err));
                shutil.rmtree(local_code_dir);#检出失败时，递归删除该目录，方便下次再次检出
                raise Exception,err;#重新抛出该异常，中断后续操作，保证只有在检出成功的情况下才继续进行        

def check_in(project,log_message):
    dist_dir = project.get_local_dist_path();
    project_name = project.get_name();
    print_log('check in ' + project_name + ' start');
    try:
        print_log('check in ' + dist_dir + ' ... ');
        add_files(dist_dir);
        client.checkin(dist_dir,log_message);    
        print_log('check in ' + project_name + ' successfully');
    except Exception,err:
        print_log('check out ' + project_name + ' failed:' + str(err));

def add_files(path):
    changes = client.status(path);
    for change in changes:
        if(change.text_status == pysvn.wc_status_kind.unversioned):
            print_log('add file:' + change.path);
            client.add(change.path);

def send_dingtalk_msg(msg,at):
    url = Config.robot_url;
    if Config.robot_url:
       data = {'msgtype' : 'text' , 'text' : { 'content' : msg }, 'at' : { 'atMobiles' : at }};
       # r = requests.post(url,json.dumps(data));
       json_dump = json.dumps(data);
       req_con = urllib2.Request(url,json_dump)
       req_con.add_header('Content-Type', 'application/json')
       response = urllib2.urlopen(req_con)
       print(response);

def auto_update():
    while True:
        for project in Config.projects:
            project_name = project.get_name();
	    try:
                need_update,version,last_author = check_need_update(project);
                if(need_update or True):
                    print_log(project_name +' new version detected:' + str(version) + ' by ' + last_author);
                    svn_update(project,version);#更新该目录至指定svn版本
                    try:                
                        target_cellphone = [];
                        phone = Config.get_cellphone_by_name(last_author);
                        if(phone):
                            target_cellphone = [phone];
                        send_dingtalk_msg('项目 ' + project_name + ' 收到你的build请求, 版本号:' + str(version) + ',正在开始build...',target_cellphone);
                        build(project);#build 该项目
                        send_dingtalk_msg('项目 ' + project_name + ' 版本号:' + str(version) + ',build 成功！',target_cellphone);
                    except Exception,err:
                        print_log(str(err));
                        send_dingtalk_msg('项目 ' + project_name + ' 版本号:' + str(version) + ',build 失败！详情请查看:https://t.xls.kuaidiantong.cn/autoBuilder/log',target_cellphone);
                        raise;
                    copy_to_dist(project);#复制生成后的文件到发布目录，主要防止生成时间过长造成发布目录访问受影响
                    check_in(project , 'auto building from version ' + str(version) + ' by ' + last_author);
                else:
                    print_log(project_name + ' no avaliable version!');
            except Exception,err:
                print_log(project_name + ' auto update error:' + str(err));
        time.sleep(Config.check_interval_seconds);

def build(project):
    project_name = project.get_name();
    try:
        print_log('build project ' + project.get_name() + ' start');
        scripts = 'npm run build --no-cache --prefix ' + project.get_local_code_path();
        run_shell_scripts(scripts);
        print_log('build project ' + project.get_name() + ' finished');
    except Exception,err:
        print_log('build project ' + project_name + ' error: ' + str(err));
        raise Exception,err;

def copy_to_dist(project):
    project_name = project.get_name();
    dist_dir = project.get_dist_path();
    src_dist_dir = project.get_local_code_path() + '/dist';#表示源码build之后的生成目录
    try:
       scripts = '';
       if os.path.exists(dist_dir):
           print_log('delete directory ' + dist_dir);
           scripts = 'rm -r ' + dist_dir;
           run_shell_scripts(scripts);  #删除发布目录
       
       print_log('copy project ' + project_name + ' distribution to ' + dist_dir + ' start');
       scripts = 'cp -r ' + src_dist_dir + ' ' + dist_dir;
       run_shell_scripts(scripts);  #拷贝源码目录中的dist至发布目录
       print_log('copy project ' + project_name + ' distribution to ' + dist_dir + ' finished');
    except Exception, err:
       print_log('copy project ' + project_name + ' distribution to ' + dist_dir + ' error: ' + str(err));

def run_shell_scripts(scripts):       
    reload(sys);
    sys.setdefaultencoding('utf-8');
    p = subprocess.Popen(scripts,shell=True,stdout=subprocess.PIPE);
    out,err = p.communicate();
    print_log(out.decode('gbk'));
    if(p.returncode != 0 ):
        raise Exception('run "' + scripts + '" error! Exit code is ' + str(p.returncode));
    print_log('run "' + scripts + '" successfully!');

def setlocale():
    language_code, encoding = locale.getdefaultlocale()
    if language_code is None:
        language_code = 'en_US'
    if encoding is None:
        encoding = 'UTF-8'
    if encoding.lower() == 'utf':
        encoding = 'UTF-8'
    locale.setlocale( locale.LC_ALL, '%s.%s' % (language_code, encoding));



if "__main__" == __name__:
    setlocale();
    # send_dingtalk_msg('ok ',['18570392802']);
    client = pysvn.Client();
    client.callback_get_login = get_login;
    ensure_checkout();
    auto_update();
    
