from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_socketio import SocketIO
import asyncio
import os
import json
import time
import argparse
import torch
from pydantic import BaseModel
from typing import List, Dict, Optional, Any

from src.client.client_factory import ClientFactory
from src.speaker_identification.preprocess.text_preprocess import TextPreprocessor
from src.speaker_identification.csi.models.pytorch_modeling import BertConfig, BertForQuestionAnswering
from src.speaker_identification.csi.evaluate.cmrc2018_output import write_predictions
from src.speaker_identification.csi.tokenizations import official_tokenization as tokenization
from src.speaker_identification.csi.preprocess.cmrc2018_preprocess import json2features
from src.speaker_identification.csi.preprocess import utils
from src.speaker_identification.csi.test_si import evaluate
from src.utils import get_text_from_file, WebSocketTqdm


app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 配置文件路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

AUDIO_DIR = os.path.join(ROOT_DIR, "cache", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

TEXT_DIR = os.path.join(ROOT_DIR, "cache", "text")
os.makedirs(TEXT_DIR, exist_ok=True)

PRED_DIR = os.path.join(ROOT_DIR, "cache", "speaker_identification")
os.makedirs(PRED_DIR, exist_ok=True)


class TTSConfig(BaseModel):
    text: str
    service: str = 'edge-tts'  # 服务类型
    config: Dict[str, Any] = {}  # 服务特定参数

class DialogConfig(BaseModel):
    narrator_voice: str = 'zh-CN-XiaoxiaoNeural'
    character_voices: Dict[str, str] = {}
    split_rules: List[str] = ['。', '！', '？', '\n']

# 初始化可用的 TTS 客户端
tts_clients = {
    'Edge TTS': ClientFactory.create('edge-tts', max_retries=3),
    # 'other_service': TTSFactory.create('other_service', **config)
}

@app.route('/api/tts', methods=['POST'])
def text_to_speech():
    try:
        tts_config = TTSConfig(**request.json)
        file_hash = hash((tts_config.text, tts_config.service, json.dumps(tts_config.config)))
        output_file = os.path.join(ROOT_DIR, AUDIO_DIR, f'{file_hash}.mp3')
        if os.path.exists(output_file):
            return jsonify({'success': True, 'audio_url': output_file})
        # 获取对应的 TTS 客户端
        client = tts_clients.get(tts_config.service)
        if not client:
            return jsonify({'success': False, 'error': f'Unsupported TTS service: {tts_config.service}'})
        
        # 使用选定的客户端进行转换
        success = asyncio.run(client.text_to_speech(
            tts_config.text,
            tts_config.config,
            output_file
        ))
        if success:
            return jsonify({'success': True, 'audio_url': output_file})
        else:
            return jsonify({'success': False, 'error': 'TTS conversion failed'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
        
@app.route('/api/split-sentences', methods=['POST'])
def split_sentences():
    """
    文本分句API
    请求体格式: {'text_dir': 文本文件路径, 'split_rule': 分句规则}
    返回格式: {
        "success": true/false,
        "sentences": ["句子1", "句子2", ...],
        "quotes_idx": [0, 1, 2, ...]
    }
    """
    try:
        data = request.json
        if not data or 'text_dir' not in data or 'split_rule' not in data:
            return jsonify({'success': False, 'error': '缺少文本参数'})
        
        text_dir = data['text_dir']
        
        text = get_text_from_file(text_dir)
        # 调用split_sentences函数
        sentences, quotes_idx = TextPreprocessor.split_sentences(text, data['split_rule'])
        # 将sentences和quotes_idx存储到文件text_dir去除后缀+_sentences.json中
        # 获取文件名（不含扩展名）和路径
        base_name = os.path.splitext(text_dir)[0]
        sentences_dir = base_name + '_sentences.json'
        with open(sentences_dir, 'w', encoding='utf-8') as f:
            json.dump({
                'sentences': sentences,
                'quotes_idx': quotes_idx
            }, f, ensure_ascii=False)

        return jsonify({
            'success': True,
            'sentences_dir': sentences_dir,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    

@app.route('/api/identify-speaker', methods=['POST'])
def identify_speaker():
    """
    识别说话人API
    请求体格式: {"sentences_dir": "分句后的文本文件路径"}
    返回格式: {
        "success": true/false,
        "nbest_dir": "识别结果文件路径"
        "prediction_dir": "预测结果文件路径"
    }
    """
    try:
        data = request.json
        if not data or 'base_dir' not in data:
            return jsonify({'success': False, 'error': 'api缺少参数'})
        
        base_dir = data['base_dir']
        pre_size = data['pre_size']
        post_size = data['post_size']
        
        sentences_dir = os.path.join(TEXT_DIR, base_dir + '_sentences.json')
        
        # 读取分句后的JSON文件
        with open(sentences_dir, 'r', encoding='utf-8') as f:
            sentences_data = json.load(f)
            sentences = sentences_data['sentences']
            quotes_idx = sentences_data['quotes_idx']
            
        # 构造CMRC格式数据集
        dataset = {
            "version": "v1.0",
            "data": []
        }
        
        for idx in quotes_idx:
            # 获取上下文
            pre_context, quote_sentence, post_context, question_context = TextPreprocessor.get_context(sentences=sentences, quote_idx=idx, pre_size=pre_size, post_size=post_size)
            
            # 构造完整上下文
            full_context = f"{pre_context} {quote_sentence} {post_context}"
            
            # 构造数据样本
            sample = {
                "paragraphs": [{
                    "id": f"sentence_{idx}",
                    "context": full_context,
                    "qas": [{
                        "question": question_context,
                        "id": f"sentence_{idx}",
                        "answers": [{
                            "text": "说话人",
                            "answer_start": 1
                        }]
                    }]
                }]
            }
            dataset["data"].append(sample)
            
        # 保存数据集
        dataset_dir = os.path.join(TEXT_DIR, base_dir + '_dataset.json')
        with open(dataset_dir, 'w', encoding='utf-8') as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        
        checkpoint_dir=os.path.join(PRED_DIR, base_dir)
        # 准备评估参数
        eval_args = argparse.Namespace(
            gpu_ids='0',
            n_batch=1,
            max_ans_length=50,
            n_best=6,
            vocab_size=21128,
            dev_dir1=os.path.join(TEXT_DIR, base_dir + '_examples.json'),
            dev_dir2=os.path.join(TEXT_DIR, base_dir + '_features.json'),
            dev_file=dataset_dir,
            bert_config_file=os.path.join(ROOT_DIR, "model/chinese-roberta-wwm-ext-large-csi-v1/config.json"),
            vocab_file=os.path.join(ROOT_DIR, "model/chinese-roberta-wwm-ext-large-csi-v1/vocab.txt"),
            init_restore_dir=os.path.join(ROOT_DIR, "model/chinese-roberta-wwm-ext-large-csi-v1/csi-v1.pth"),
            checkpoint_dir=checkpoint_dir
        )
        
        # 设置GPU
        os.environ["CUDA_VISIBLE_DEVICES"] = eval_args.gpu_ids
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # 加载BERT配置
        bert_config = BertConfig.from_json_file(eval_args.bert_config_file)
        
        # 加载分词器
        tokenizer = tokenization.BertTokenizer(vocab_file=eval_args.vocab_file, do_lower_case=True)
        
        # if not os.path.exists(eval_args.dev_dir1) or not os.path.exists(eval_args.dev_dir2):
        #     print('Converting examples to features...')
        #     # 进行特征提取
        #     json2features(eval_args.dev_file, 
        #                 [eval_args.dev_dir1, eval_args.dev_dir2], 
        #                 tokenizer, 
        #                 is_training=False,
        #                 max_seq_length=bert_config.max_position_embeddings)
        # 进行特征提取
        json2features(eval_args.dev_file, 
                    [eval_args.dev_dir1, eval_args.dev_dir2], 
                    tokenizer, 
                    is_training=False,
                    max_seq_length=bert_config.max_position_embeddings)
        
        # 加载开发集数据
        dev_examples = json.load(open(eval_args.dev_dir1, 'r', encoding='utf-8'))
        dev_features = json.load(open(eval_args.dev_dir2, 'r', encoding='utf-8'))
        
        # 初始化模型
        model = BertForQuestionAnswering(bert_config)
        utils.torch_init_model(model, eval_args.init_restore_dir)
        model.to(device)
        
        # 生成唯一的任务ID
        task_id = str(time.time())
        # 进行评估，传入socketio和task_id
        evaluate(model, eval_args, dev_examples, dev_features, device, socketio=socketio, task_id=task_id)
        
        # 返回结果路径
        prediction_path = os.path.join(checkpoint_dir, "predictions.json")
        nbest_path = os.path.join(checkpoint_dir, "nbest.json")
        
        return jsonify({
            'success': True,
            'speakers_dir': prediction_path,
            'nbest_dir': nbest_path
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/voices')
def get_voices():
    # 这里可以扩展为动态获取可用声音列表
    voices = [
        {'id': 'zh-CN-XiaoxiaoNeural', 'name': '晓晓（女）'},
        {'id': 'zh-CN-YunxiNeural', 'name': '云希（男）'},
        {'id': 'zh-CN-YunjianNeural', 'name': '云健（男）'},
        {'id': 'zh-CN-XiaoyiNeural', 'name': '晓伊（女）'},
        {'id': 'zh-CN-YunyangNeural', 'name': '云扬（男）'}
    ]
    return jsonify(voices)

# 添加静态文件服务路由
@app.route('/cache/audio/<path:filename>')
def serve_audio(filename):
    return send_file(os.path.join(AUDIO_DIR, filename))

if __name__ == '__main__':
    
    app.run(
        host='localhost',  
        port=10032,
        debug=True
    )