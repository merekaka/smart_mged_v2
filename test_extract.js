/**
 * 从原始 JSON 数据中提取元素组成信息，用于饼图展示
 * 原始数据中的化学成分格式：
 *   "化学成分": [
 *     {"成分": "Al", "含量（wt%）": "5.15"},
 *     {"成分": "Ti", "含量（wt%）": "余量"}
 *   ]
 */
function extractElementComposition(rawData) {
    var dataContent = rawData.data || {};
    var chemComponents = null;
    
    // 查找化学成分字段（可能是"化学成分"或其他键）
    for (var key in dataContent) {
        if (dataContent.hasOwnProperty(key) && key.indexOf('化学') >= 0 && Array.isArray(dataContent[key])) {
            chemComponents = dataContent[key];
            break;
        }
    }
    
    if (!chemComponents || chemComponents.length === 0) {
        return null;
    }
    
    var elements = [];
    var knownSum = 0.0;
    var remainderElem = null;
    
    for (var i = 0; i < chemComponents.length; i++) {
        var item = chemComponents[i];
        var name = item['成分'] || '';
        var valStr = item['含量（wt%）'] || item['含量'] || '';
        
        if (!name) continue;
        
        // 解析数值
        var val = parseFloat(valStr);
        if (isNaN(val)) {
            // 可能是"余量"
            if (valStr.indexOf('余') >= 0) {
                remainderElem = name;
            }
            continue;
        }
        
        // 处理范围格式（如 "2.0~3.0"）
        if (valStr.indexOf('~') >= 0 || valStr.indexOf('-') >= 0) {
            var parts = valStr.split(/[~\-]/);
            if (parts.length === 2) {
                var left = parseFloat(parts[0]);
                var right = parseFloat(parts[1]);
                if (!isNaN(left) && !isNaN(right)) {
                    val = (left + right) / 2;
                }
            }
        }
        
        elements.push({
            name: name,
            value: val,
            raw: valStr
        });
        knownSum += val;
    }
    
    if (elements.length === 0) {
        return null;
    }
    
    // 处理余量
    if (remainderElem) {
        var remainder = Math.max(0, 100 - knownSum);
        elements.push({
            name: remainderElem,
            value: remainder,
            raw: '余量',
            is_remainder: true
        });
    }
    
    // 按含量排序
    elements.sort(function(a, b) { return b.value - a.value; });
    
    return {
        has_composition: true,
        elements: elements,
        total_known: knownSum
    };
}
