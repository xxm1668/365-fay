import sqlite3
import time
import threading
import functools
def synchronized(func):
  @functools.wraps(func)
  def wrapper(self, *args, **kwargs):
    with self.lock:
      return func(self, *args, **kwargs)
  return wrapper
class Content_Db:

    def __init__(self) -> None:
        self.lock = threading.Lock()
           
   

    #初始化
    def init_db(self):
        conn = sqlite3.connect('fay.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE T_Msg
            (id INTEGER PRIMARY KEY     autoincrement,
            type        char(10),
            way        char(10),
            content           TEXT    NOT NULL,
            createtime         Int);''')
        conn.commit()
        conn.close()
       
 


    #添加对话
    @synchronized
    def add_content(self,type,way,content):
        conn = sqlite3.connect("fay.db")
        cur = conn.cursor()
        cur.execute("insert into T_Msg (type,way,content,createtime) values (?,?,?,?)",(type,way,content,int(time.time())))
        
        conn.commit()
        conn.close()
        return cur.lastrowid
     
        

    #获取对话内容
    @synchronized
    def get_list(self,way,order,limit):
        conn = sqlite3.connect("fay.db")
        cur = conn.cursor()
        if(way == 'all'):
            cur.execute("select type,way,content,createtime,datetime(createtime, 'unixepoch', 'localtime') as timetext from T_Msg  order by id "+order+" limit ?",(limit,))
        elif(way == 'notappended'):
            cur.execute("select type,way,content,createtime,datetime(createtime, 'unixepoch', 'localtime') as timetext from T_Msg where way != 'appended' order by id "+order+" limit ?",(limit,))
        else:
            cur.execute("select type,way,content,createtime,datetime(createtime, 'unixepoch', 'localtime') as timetext from T_Msg where way = ? order by id "+order+" limit ?",(way,limit,))

        list = cur.fetchall()
        conn.close()
        return list





# a = Content_Db()
# s = a.get_list('all','desc',10)
# print(s)
   





   



