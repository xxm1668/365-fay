import asyncio
import websockets
import time
from queue import Queue
import threading
import argparse
import json
from modelscope.pipelines import pipeline
from modelscope.utils.constant import Tasks
from modelscope.utils.logger import get_logger
import logging
import tracemalloc
import functools
tracemalloc.start()

logger = get_logger(log_level=logging.CRITICAL)
logger.setLevel(logging.CRITICAL)


websocket_users = set()  #维护客户端列表

parser = argparse.ArgumentParser()
parser.add_argument("--host",
                    type=str,
                    default="0.0.0.0",
                    required=False,
                    help="host ip, localhost, 0.0.0.0")
parser.add_argument("--port",
                    type=int,
                    default=10197,
                    required=False,
                    help="grpc server port")
parser.add_argument("--model",
                    type=str,
                    default="./data/speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404",
                    help="model from modelscope")
parser.add_argument("--vad_model",
                    type=str,
                    default="damo/speech_fsmn_vad_zh-cn-16k-common-pytorch",
                    help="model from modelscope")
parser.add_argument("--punc_model",
                    type=str,
                    default="",
                    help="model from modelscope")
parser.add_argument("--ngpu",
                    type=int,
                    default=1,
                    help="0 for cpu, 1 for gpu")

args = parser.parse_args()

print("model loading")
# asr
param_dict_asr = {}
param_dict_asr['hotword']="data/hotword.txt"
inference_pipeline_asr = pipeline(
    task=Tasks.auto_speech_recognition,
    model=args.model,
    param_dict=param_dict_asr,
    ngpu=args.ngpu
)
if args.punc_model != "":
    # param_dict_punc = {'cache': list()}
    inference_pipeline_punc = pipeline(
        task=Tasks.punctuation,
        model=args.punc_model,
        model_revision=None,
        ngpu=args.ngpu,
    )
else:
    inference_pipeline_punc = None


# vad
inference_pipeline_vad = pipeline(
    task=Tasks.voice_activity_detection,
    model=args.vad_model,
    model_revision='v1.2.0',
    output_dir=None,
    batch_size=1,
    mode='online',
    ngpu=args.ngpu,
)
print("model loaded")


def vad(data, websocket):  # VAD推理
    global inference_pipeline_vad
    segments_result = inference_pipeline_vad(audio_in=data, param_dict=websocket.param_dict_vad)
    speech_start = False
    speech_end = False

    if len(segments_result) == 0 or len(segments_result["text"]) > 1:
        return speech_start, speech_end
    if segments_result["text"][0][0] != -1:
        speech_start = True
    if segments_result["text"][0][1] != -1:
        speech_end = True
    return speech_start, speech_end


async def ws_serve(websocket,path):

    frames = []  # 存储所有的帧数据
    buffer = []  # 存储缓存中的帧数据（最多两个片段）
    RECORD_NUM = 0
    global websocket_users
    speech_start, speech_end = False, False
    # 调用asr函数
    websocket.param_dict_vad = {'in_cache': dict(), "is_final": False}
    websocket.param_dict_punc = {'cache': list()}
    websocket.speek = Queue()  # websocket 添加进队列对象 让asr读取语音数据包
    websocket.send_msg = Queue()  # websocket 添加个队列对象  让ws发送消息到客户端
    websocket_users.add(websocket)
    ss = threading.Thread(target=asr, args=(websocket,))
    ss.start()
    try:
        async for message in websocket:
            if (type(message) == str):
                dict_message = json.loads(message)
                if dict_message['vad_need'] == True:
                    vad_method = True
                else:
                    vad_method = False
            if vad_method == True:
                if type(message) != str:
                    buffer.append(message)
                if len(buffer) > 2:
                    buffer.pop(0)  # 如果缓存超过两个片段，则删除最早的一个

                if speech_start:
                    frames.append(message)
                    RECORD_NUM += 1
                if type(message) != str:
                    speech_start_i, speech_end_i = vad(message, websocket)
                    # print(speech_start_i, speech_end_i)
                    if speech_start_i:
                        speech_start = speech_start_i
                        frames = []
                        frames.extend(buffer)  # 把之前2个语音数据快加入
                    if speech_end_i or RECORD_NUM > 300:
                        speech_start = False
                        audio_in = b"".join(frames)
                        websocket.speek.put(audio_in)
                        frames = []  # 清空所有的帧数据
                        buffer = []  # 清空缓存中的帧数据（最多两个片段）
                        RECORD_NUM = 0
                    if not websocket.send_msg.empty():
                        await websocket.send(websocket.send_msg.get())
                        websocket.send_msg.task_done()
            else:
                if speech_start :
                    frames.append(message)
                    RECORD_NUM += 1
                if (type(message) == str):
                    dict_message = json.loads(message)
                    if dict_message['vad_need'] == False and dict_message['state'] == 'StartTranscription':
                        speech_start = True
                    elif dict_message['vad_need'] == False and dict_message['state'] == 'StopTranscription':
                        speech_start = False
                        speech_end = True
                        if len(frames) != 0:
                            frames.pop()
                if speech_end or RECORD_NUM > 1024:
                    speech_start = False
                    speech_end = False
                    audio_in = b"".join(frames)
                    websocket.speek.put(audio_in)
                    frames = []  # 清空所有的帧数据
                    RECORD_NUM = 0
                    await websocket.send(websocket.send_msg.get())
                    websocket.send_msg.task_done()
    except websockets.ConnectionClosed:
        print("ConnectionClosed...", websocket_users)    # 链接断开
        websocket_users.remove(websocket)
    except websockets.InvalidState:
        print("InvalidState...")    # 无效状态
    except Exception as e:
        print("Exception:", e)

 

def asr(websocket):  # ASR推理
        global inference_pipeline_asr, inference_pipeline_punc
        # global param_dict_punc
        global websocket_users
        while websocket in  websocket_users:
            # if not websocket.speek.empty():
            audio_in = websocket.speek.get()
            websocket.speek.task_done()
            if len(audio_in) > 0:
                rec_result = inference_pipeline_asr(audio_in=audio_in)
                if "text" in rec_result:
                    websocket.send_msg.put(rec_result["text"]) # 存入发送队列  直接调用send发送不了
            time.sleep(0.1)

start_server = websockets.serve(ws_serve, args.host, args.port, subprotocols=["binary"], ping_interval=None)
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()