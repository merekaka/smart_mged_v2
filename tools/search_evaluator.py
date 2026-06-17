"""
搜索质量评估工具
----------------
用于评估向量搜索、意图理解等搜索功能的正确率和质量

使用方法:
    # 1. 准备测试集 (data/evaluation/test_queries.json)
    # 2. 运行评估
    python tools/search_evaluator.py --model m3e-base --topk 20
    
    # 3. 生成报告
    python tools/search_evaluator.py --report results/eval_20240101.json
"""

import json
import time
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import numpy as np

# 设置 Django 环境
import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from apps.search.services import vector_search
from core.model_loader import get_model, get_data

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class EvalMetrics:
    """评估指标数据类"""
    query: str
    topk: int
    
    # 基础指标
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    
    # 排名指标
    mrr: float = 0.0  # Mean Reciprocal Rank
    ndcg_at_k: float = 0.0  # Normalized DCG
    
    # 效率指标
    response_time: float = 0.0
    encode_time: float = 0.0
    search_time: float = 0.0
    
    # 详细结果
    retrieved_ids: List[str] = None
    relevant_ids: List[str] = None
    
    def __post_init__(self):
        if self.retrieved_ids is None:
            self.retrieved_ids = []
        if self.relevant_ids is None:
            self.relevant_ids = []


class SearchEvaluator:
    """搜索质量评估器"""
    
    def __init__(self, model_name: str = "m3e-base", abstract_mode: str = "external"):
        self.model_name = model_name
        self.abstract_mode = abstract_mode
        self.faiss_index = None
        self.abstract_ids = None
        self.abstracts = None
        self.model = None
        
    def initialize(self):
        """初始化搜索组件"""
        logger.info(f"初始化搜索组件 - 模型: {self.model_name}")
        self.faiss_index, self.abstract_ids, self.abstracts = get_data(
            self.model_name, self.abstract_mode
        )
        self.model = get_model(self.model_name)
        logger.info(f"索引加载完成 - 共 {len(self.abstract_ids)} 条数据")
        
    def calculate_metrics(
        self, 
        query: str,
        relevant_ids: List[str],
        topk: int = 20
    ) -> EvalMetrics:
        """
        计算单个查询的评估指标
        
        Args:
            query: 查询文本
            relevant_ids: 相关的数据集ID列表（人工标注或自动生成的参考答案）
            topk: 评估前K个结果
            
        Returns:
            EvalMetrics: 评估指标
        """
        metrics = EvalMetrics(query=query, topk=topk, relevant_ids=relevant_ids)
        
        # 执行搜索
        start_time = time.time()
        results, timing = vector_search(
            query, 
            self.faiss_index, 
            self.model,
            self.abstracts, 
            self.abstract_ids, 
            k=topk
        )
        metrics.response_time = time.time() - start_time
        metrics.encode_time = timing.get("encode_time", 0)
        metrics.search_time = timing.get("search_time", 0)
        
        if not results:
            logger.warning(f"查询无结果: {query}")
            return metrics
        
        # 获取检索到的ID
        retrieved_ids = [str(r["id"]) for r in results]
        metrics.retrieved_ids = retrieved_ids
        
        # 计算 Precision@K
        relevant_set = set(relevant_ids)
        retrieved_set = set(retrieved_ids)
        relevant_retrieved = relevant_set & retrieved_set
        
        metrics.precision_at_k = len(relevant_retrieved) / len(retrieved_ids) if retrieved_ids else 0
        metrics.recall_at_k = len(relevant_retrieved) / len(relevant_ids) if relevant_ids else 0
        
        # 计算 MRR (Mean Reciprocal Rank)
        for i, rid in enumerate(retrieved_ids):
            if rid in relevant_set:
                metrics.mrr = 1.0 / (i + 1)
                break
        
        # 计算 NDCG@K
        metrics.ndcg_at_k = self._calculate_ndcg(retrieved_ids, relevant_ids, topk)
        
        return metrics
    
    def _calculate_ndcg(self, retrieved_ids: List[str], relevant_ids: List[str], k: int) -> float:
        """计算 NDCG@K"""
        relevant_set = set(relevant_ids)
        
        # 计算 DCG
        dcg = 0.0
        for i, rid in enumerate(retrieved_ids[:k]):
            if rid in relevant_set:
                # 使用对数折扣
                dcg += 1.0 / np.log2(i + 2)  # i+2 because log2(1)=0, rank starts at 1
        
        # 计算理想 DCG (IDCG)
        idcg = 0.0
        for i in range(min(len(relevant_ids), k)):
            idcg += 1.0 / np.log2(i + 2)
        
        return dcg / idcg if idcg > 0 else 0.0
    
    def evaluate_batch(
        self, 
        test_queries: List[Dict[str, Any]], 
        topk: int = 20
    ) -> Dict[str, Any]:
        """
        批量评估测试集
        
        Args:
            test_queries: 测试查询列表
                格式: [{"query": "...", "relevant_ids": ["id1", "id2"], "description": "..."}]
            topk: 评估前K个结果
            
        Returns:
            评估报告
        """
        if self.faiss_index is None:
            self.initialize()
        
        results = []
        logger.info(f"开始评估 {len(test_queries)} 个查询...")
        
        for i, item in enumerate(test_queries):
            query = item.get("query", "")
            relevant_ids = [str(rid) for rid in item.get("relevant_ids", [])]
            description = item.get("description", "")
            
            logger.info(f"[{i+1}/{len(test_queries)}] 评估: {query[:50]}...")
            
            metrics = self.calculate_metrics(query, relevant_ids, topk)
            results.append(asdict(metrics))
        
        # 计算平均指标
        avg_metrics = self._calculate_average_metrics(results)
        
        report = {
            "summary": {
                "model": self.model_name,
                "abstract_mode": self.abstract_mode,
                "topk": topk,
                "total_queries": len(test_queries),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                **avg_metrics
            },
            "details": results
        }
        
        return report
    
    def _calculate_average_metrics(self, results: List[Dict]) -> Dict[str, float]:
        """计算平均指标"""
        if not results:
            return {}
        
        avg = {}
        numeric_fields = [
            "precision_at_k", "recall_at_k", "mrr", "ndcg_at_k",
            "response_time", "encode_time", "search_time"
        ]
        
        for field in numeric_fields:
            values = [r.get(field, 0) for r in results if r.get(field) is not None]
            avg[field] = round(np.mean(values), 4) if values else 0.0
            avg[f"{field}_std"] = round(np.std(values), 4) if values else 0.0
        
        return avg
    
    def generate_report(self, report: Dict[str, Any], output_path: str = None):
        """生成并保存评估报告"""
        summary = report["summary"]
        
        # 控制台输出
        print("\n" + "="*60)
        print("搜索质量评估报告")
        print("="*60)
        print(f"模型: {summary['model']}")
        print(f"摘要模式: {summary['abstract_mode']}")
        print(f"评估数量: {summary['total_queries']} 个查询")
        print(f"评估TopK: {summary['topk']}")
        print(f"评估时间: {summary['timestamp']}")
        print("-"*60)
        print("平均指标:")
        print(f"  Precision@{summary['topk']}: {summary.get('precision_at_k', 0):.4f}")
        print(f"  Recall@{summary['topk']}:    {summary.get('recall_at_k', 0):.4f}")
        print(f"  MRR:           {summary.get('mrr', 0):.4f}")
        print(f"  NDCG@{summary['topk']}:      {summary.get('ndcg_at_k', 0):.4f}")
        print("-"*60)
        print("效率指标:")
        print(f"  平均响应时间: {summary.get('response_time', 0)*1000:.2f} ms")
        print(f"  编码时间:     {summary.get('encode_time', 0)*1000:.2f} ms")
        print(f"  搜索时间:     {summary.get('search_time', 0)*1000:.2f} ms")
        print("="*60)
        
        # 保存到文件
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            logger.info(f"报告已保存: {output_path}")
        
        return report


def create_sample_test_set():
    """创建示例测试集"""
    sample_queries = [
        {
            "query": "铝合金的抗拉强度",
            "relevant_ids": ["铝合金数据", "铝合金材料韧性损伤的模拟数据", "铝合金纳米力学实验数据"],
            "description": "铝合金力学性能查询"
        },
        {
            "query": "高温合金的化学成分",
            "relevant_ids": ["高温合金文本挖掘数据", "镍基单晶高温合金研究论文元数据", "钴基高温合金成分与相组成"],
            "description": "高温合金成分查询"
        },
        {
            "query": "钙钛矿太阳能电池性能",
            "relevant_ids": ["钙钛矿实验-性能值", "钙钛矿电池性能参数", "钙钛矿性能数据-V4"],
            "description": "钙钛矿性能查询"
        },
        {
            "query": "钢铁的弹性模量",
            "relevant_ids": ["特殊钢-物理性能-弹性模量", "特殊钢-模具钢-弹性模量"],
            "description": "钢铁力学性能查询"
        },
        {
            "query": "陶瓷材料的热导率",
            "relevant_ids": ["陶瓷膜产品性能检测", "陶瓷涂层材料——生产"],
            "description": "陶瓷热性能查询"
        }
    ]
    return sample_queries


def create_advanced_test_set():
    """创建更复杂的测试集（包含更多查询变体）"""
    advanced_queries = [
        # 材料-性能组合
        {
            "query": "钛合金的屈服强度",
            "relevant_ids": ["钛合金数据模板"],
            "description": "钛合金力学性能"
        },
        {
            "query": "镁合金的腐蚀性能",
            "relevant_ids": ["Mg_H_ads", "Mg_bin_E"],
            "description": "镁合金腐蚀性能"
        },
        {
            "query": "核材料的辐照性能",
            "relevant_ids": ["RPV材料辐照样品纳米压痕数据", "RPV材料辐照纳米压痕数据-模量"],
            "description": "核材料性能"
        },
        # 工艺相关
        {
            "query": "热处理工艺对性能的影响",
            "relevant_ids": ["高温合金动力学数据", "高温合金析出相尺寸"],
            "description": "热处理工艺"
        },
        {
            "query": "3D打印增材制造材料",
            "relevant_ids": ["3D晶粒信息汇总"],
            "description": "增材制造"
        },
        # 计算模拟
        {
            "query": "第一性原理计算数据",
            "relevant_ids": ["第一性计算数据", "ab-crystallib高通量计算无机基质数据库"],
            "description": "第一性原理"
        },
        {
            "query": "分子动力学模拟结果",
            "relevant_ids": ["环氧树脂基复合材料高通量计算数据-- Forcite Dynamics"],
            "description": "分子动力学"
        },
        # 英文查询
        {
            "query": "perovskite solar cell efficiency",
            "relevant_ids": ["钙钛矿电池性能参数", "钙钛矿实验-性能值"],
            "description": "英文查询-钙钛矿"
        },
        {
            "query": "superalloy creep properties",
            "relevant_ids": ["高温合金文本挖掘数据", "镍基单晶高温合金研究论文元数据"],
            "description": "英文查询-高温合金"
        }
    ]
    return advanced_queries


def main():
    parser = argparse.ArgumentParser(description='搜索质量评估工具')
    parser.add_argument('--model', default='m3e-base', help='模型名称 (m3e-base/m3e-large)')
    parser.add_argument('--abstract-mode', default='external', help='摘要模式')
    parser.add_argument('--topk', type=int, default=20, help='评估TopK')
    parser.add_argument('--test-file', help='测试集JSON文件路径')
    parser.add_argument('--output', '-o', help='输出报告路径')
    parser.add_argument('--report', help='查看已生成的报告文件')
    parser.add_argument('--sample', action='store_true', help='使用示例测试集')
    parser.add_argument('--advanced', action='store_true', help='使用高级测试集')
    
    args = parser.parse_args()
    
    # 查看已有报告
    if args.report:
        with open(args.report, 'r', encoding='utf-8') as f:
            report = json.load(f)
        evaluator = SearchEvaluator()
        evaluator.generate_report(report)
        return
    
    # 准备测试集
    if args.test_file:
        with open(args.test_file, 'r', encoding='utf-8') as f:
            test_queries = json.load(f)
    elif args.advanced:
        test_queries = create_advanced_test_set()
    else:
        test_queries = create_sample_test_set()
    
    # 运行评估
    evaluator = SearchEvaluator(args.model, args.abstract_mode)
    report = evaluator.evaluate_batch(test_queries, args.topk)
    
    # 生成报告
    if not args.output:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        args.output = f"results/eval_{args.model}_{timestamp}.json"
    
    evaluator.generate_report(report, args.output)


if __name__ == '__main__':
    main()
