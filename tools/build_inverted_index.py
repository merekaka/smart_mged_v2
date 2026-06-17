"""
构建倒排索引：从 ids_m3e-base_normalized.json 中提取文本关键词并统计
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

try:
    import jieba
except ImportError:
    print("需要安装 jieba: pip install jieba")
    sys.exit(1)


def build_inverted_index(json_file_path, output_file_path=None):
    """
    从 JSON 文件构建倒排索引
    
    Args:
        json_file_path: 输入的 JSON 文件路径
        output_file_path: 输出的倒排索引文件路径（可选）
    
    Returns:
        倒排索引字典: {keyword: {chunk_id: count, ...}, ...}
    """
    
    # 加载 JSON 文件
    print(f"正在加载: {json_file_path}")
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"总记录数: {len(data)}")
    
    # 构建倒排索引
    inverted_index = defaultdict(lambda: defaultdict(int))
    
    # 停用词集合（可根据需要扩展）
    stopwords = {
        '的', '了', '和', '是', '在', '到', '一', '了', '或', '、',
        '，', '。', '！', '？', '；', '：', '（', '）', '"', '"',
        '等', '其他', '此', '该', '此外', '否则', '除', '按', '根据',
        '本', '本法', '为了', '结合', '制定', '任务', '保护', '以',
        '维护', '明文', '规定', '不', '得', '无', '有', '人'
    }
    
    # 处理每条记录
    for idx, record in enumerate(data):
        if idx % 10000 == 0:
            print(f"已处理: {idx}/{len(data)}")
        
        chunk_id = record.get('id', '')
        text = record.get('text', '')
        
        if not text:
            continue
        
        # 中文分词
        words = jieba.cut(text, cut_all=False)
        
        # 统计词频，跳过停用词和单个字符
        for word in words:
            # 跳过停用词、纯空白、单个字符
            if word.strip() and word not in stopwords and len(word) > 1:
                inverted_index[word][chunk_id] += 1
    
    print(f"唯一关键词数: {len(inverted_index)}")
    
    # 生成统计结果
    stats = {}
    for keyword, chunks in inverted_index.items():
        stats[keyword] = {
            'total_count': sum(chunks.values()),  # 总出现次数
            'chunk_count': len(chunks),            # 出现的块数
            'chunks': chunks                       # 详细的块信息
        }
    
    # 按总出现次数排序
    sorted_stats = dict(sorted(
        stats.items(),
        key=lambda x: x[1]['total_count'],
        reverse=True
    ))
    
    # 打印前 50 个高频关键词
    print("\n=== 前 50 个高频关键词 ===")
    for i, (keyword, info) in enumerate(list(sorted_stats.items())[:50], 1):
        print(f"{i:3d}. {keyword:15s} - 总数: {info['total_count']:5d}, 块数: {info['chunk_count']:5d}")
    
    # 保存倒排索引到文件
    if output_file_path is None:
        output_file_path = str(Path(json_file_path).parent / 'inverted_index_m3e-base.json')
    
    print(f"\n正在保存倒排索引到: {output_file_path}")
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(sorted_stats, f, ensure_ascii=False, indent=2)
    
    print("✓ 倒排索引保存完成")
    
    return sorted_stats


def print_keyword_details(stats, keyword):
    """打印特定关键词的详细信息"""
    if keyword in stats:
        info = stats[keyword]
        print(f"\n关键词: {keyword}")
        print(f"  总出现次数: {info['total_count']}")
        print(f"  出现的块数: {info['chunk_count']}")
        print(f"  详细分布:")
        for chunk_id, count in sorted(
            info['chunks'].items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]:
            print(f"    {chunk_id}: {count}")
    else:
        print(f"关键词 '{keyword}' 不存在")


if __name__ == '__main__':
    # 输入文件路径
    input_file = r'd:\Desktop\Himmel\coding\graduate_project\laws_ids\laws_ids_chunked\ids_m3e-base_normalized.json'
    output_file = r'd:\Desktop\Himmel\coding\graduate_project\inverted_index_m3e-base.json'
    
    # 构建倒排索引
    inverted_index = build_inverted_index(input_file, output_file)
    
    # 示例：查询特定关键词
    print("\n=== 示例查询 ===")
    print_keyword_details(inverted_index, '犯罪')
    print_keyword_details(inverted_index, '法律')
    print_keyword_details(inverted_index, '刑罚')
