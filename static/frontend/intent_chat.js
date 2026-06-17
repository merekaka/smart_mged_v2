/**
 * 数据检索对话页面 - 前端逻辑
 * 对接 /api/chat/conversations，支持服务端持久化的多轮对话
 */

const API_BASE_URL = window.location.origin;

let conversations = [];
let currentConversationId = null;
let currentMode = 'intent'; // 'intent' | 'graph'

// ==================== 结构化查询可读化映射表 ====================
const FIELD_NAME_MAP = {
    // 力学性能
    tensile_strength: "抗拉强度",
    yield_strength: "屈服强度",
    upper_yield_strength: "上屈服强度",
    lower_yield_strength: "下屈服强度",
    elastic_modulus: "弹性模量",
    compressive_modulus: "压缩模量",
    shear_modulus: "剪切模量",
    compressive_strength: "抗压强度",
    shear_strength: "抗剪强度",
    fatigue_strength: "疲劳强度",
    creep_strength: "蠕变强度",
    creep_rupture_strength: "持久强度",
    fracture_toughness: "断裂韧度",
    hardness: "硬度",
    hardness_hv: "维氏硬度",
    hardness_hrc: "洛氏硬度",
    hardness_hb: "布氏硬度",
    impact_toughness: "冲击韧性",
    impact_energy: "冲击吸收能量",
    elongation: "断后伸长率",
    reduction_area: "断面收缩率",
    poisson_ratio: "泊松比",
    // 物理性能
    density: "密度",
    melting_point: "熔点",
    thermal_conductivity: "导热系数",
    thermal_diffusivity: "热扩散率",
    thermal_expansion: "线膨胀系数",
    electrical_resistivity: "电阻率",
    specific_heat: "比热容",
    viscosity: "黏度",
    // 化学成分（主量元素）
    C: "碳(C)含量", Si: "硅(Si)含量", Mn: "锰(Mn)含量",
    P: "磷(P)含量", S: "硫(S)含量", Cr: "铬(Cr)含量",
    Ni: "镍(Ni)含量", Mo: "钼(Mo)含量", V: "钒(V)含量",
    Ti: "钛(Ti)含量", Al: "铝(Al)含量", Cu: "铜(Cu)含量",
    W: "钨(W)含量", Co: "钴(Co)含量", Nb: "铌(Nb)含量",
    B: "硼(B)含量", N: "氮(N)含量", Fe: "铁(Fe)含量",
    Mg: "镁(Mg)含量", Zn: "锌(Zn)含量", Zr: "锆(Zr)含量",
    // 晶粒与组织
    grain_size: "晶粒尺寸",
    grain_radius: "晶粒半径",
    grain_position: "晶粒位置",
    microstructure: "显微组织",
    phase_structure: "相结构",
    gamma_prime_size: "γ'相尺寸",
    gamma_prime_volume_fraction: "γ'相体积分数",
    // 腐蚀与环境
    corrosion_rate: "腐蚀速率",
    accumulated_corrosion_depth: "累计腐蚀深度",
    open_circuit_potential: "开路电位",
    polarization_resistance: "极化电阻",
    ct_corrosion_potential: "CT试样腐蚀电位",
    pt_corrosion_potential: "PT电极腐蚀电位",
    pH: "pH值",
    chloride_concentration: "氯离子浓度",
    boron_concentration: "硼浓度",
    humidity: "湿度",
    temperature: "温度",
    dissolved_O_concentration: "溶解氧浓度",
    dissolved_H_concentration: "溶解氢浓度",
    // 辐照
    irradiation_dose: "辐照剂量",
    irradiation_temperature: "辐照温度",
    irradiation_source: "辐照源",
    // 纳米压痕
    nanoindentation_hardness: "纳米压痕硬度",
    nanoindentation_modulus: "纳米压痕模量",
    indentation_depth: "压入深度",
    // 热电
    seebeck_coefficient_p_type: "p型泽贝克系数",
    seebeck_coefficient_n_type: "n型泽贝克系数",
    carrier_concentration_p_type: "p型载流子浓度",
    carrier_concentration_n_type: "n型载流子浓度",
    electrical_conductivity_p_type: "p型电导率",
    electrical_conductivity_n_type: "n型电导率",
    electronic_thermal_conductivity_p_type: "p型电子热导率",
    electronic_thermal_conductivity_n_type: "n型电子热导率",
    // 样品与材料信息
    material_name: "材料名称",
    sample_code: "试样编号",
    sample_name: "试样名称",
    sample_size: "试样尺寸",
    sample_type: "试样类型",
    specimen_type: "试样类型",
    batch_id: "炉号/批次",
    material_condition: "材料状态",
    classification: "材料分类",
    standard: "执行标准",
    supplier: "供应商",
    // 工艺
    heat_treatment_type: "热处理类型",
    heat_treatment_temperature: "热处理温度",
    heat_treatment_time: "热处理时间",
    cooling_method: "冷却方式",
    quenching_process: "淬火工艺",
    tempering_process: "回火工艺",
    normalizing_process: "正火工艺",
    quenching_and_tempering_process: "调质工艺",
    stress_relief_process: "除应力处理",
    heat_treatment_state_1: "第一热处理状态",
    heat_treatment_state_2: "第二热处理状态",
    pre_treatment_process: "预处理工艺",
    // 测试信息
    test_condition: "测试条件",
    test_method: "试验方法",
    test_standard: "试验标准",
    testing_institution: "试验单位",
    test_date: "试验日期",
    loading_condition: "加载条件",
    strain: "应变",
    stress: "应力",
    shear_rate: "剪切速率",
    shear_stress: "剪切应力",
    // 通用
    remarks: "备注",
    data_value: "数据值",
    data_description: "数据说明",
    // 流变
    rheological_modulus: "流变模量",
    // 位置
    relative_position_x: "相对位置X",
    relative_position_y: "相对位置Y",
    // 其他
    application: "用途",
    coating: "表面涂层",
    surface_condition: "表面状态",
    product_form: "产品形态",
    product_category: "品种/类别",
    production_process: "生产工艺",
    chemical_formula: "化学式",
    corresponding_grade: "等效牌号",
    diffusion_layer_depth: "扩散层深度",
    martensite_start_temperature: "马氏体转变温度(Ms)",
    crack_growth_rate: "裂纹扩展速率",
    stress_intensity_factor: "应力强度因子K",
    collection_time: "数据采集时间",
    latitude: "纬度",
    longitude: "经度",
    location_name: "采集地点",
    inclusion_rating: "夹杂物评级",
    macro_inspection: "低倍检验",
    notch_shape: "缺口形状",
    symbol: "标尺符号",
    process_code: "工艺代号",
    process_description: "工艺说明",
    calculation_model: "计算模型",
    external_database_id: "外部数据库ID",
    maximum_grain_size: "最大晶粒度",
    grain_average_width: "晶粒平均宽度",
    grain_face_count: "晶粒面数",
    grain_id: "晶粒编号",
    grain_surface_area: "晶粒表面积",
    grain_volume: "晶粒体积",
    dimension_1: "第一尺寸参数",
    dimension_2: "第二尺寸参数",
    measurement_index1: "测次1",
    measurement_index2: "测次2",
    measurement_index3: "测次3",
    measurement_index4: "测次4",
    measurement_index5: "测次5",
    sample_count: "样品数量",
    sampling_direction: "取样方向",
};

const AGG_FUNC_MAP = {
    max: "最大值",
    min: "最小值",
    avg: "平均值",
    sum: "总和",
    count: "计数",
    variance: "方差",
};

// 处理带后缀的聚合函数名（如 max_n → max）
function normalizeAggFunc(aggFunc) {
    if (!aggFunc) return aggFunc;
    // 去掉 _n 后缀（如 max_1 → max）
    return aggFunc.replace(/_\d+$/, '');
}

const OP_TEXT_MAP = {
    "=": "等于",
    ">": "大于",
    "<": "小于",
    ">=": "大于等于",
    "<=": "小于等于",
    contains: "包含",
    "!=": "不等于",
    null: "",
};

function fieldToName(field) {
    return FIELD_NAME_MAP[field] || field;
}

function formatCondValue(value, unit) {
    if (value === null || value === undefined) return "—";
    let s = String(value);
    if (unit) s += " " + unit;
    return s;
}

function conditionToReadableHTML(c, sq) {
    // 聚合查询：根据整体意图生成自然语言描述
    if (c.agg_func) {
        return buildAggConditionHTML(c, sq);
    }
    // 普通比较
    const opText = OP_TEXT_MAP[c.operator] || c.operator || "";
    const valText = formatCondValue(c.value, c.unit);
    return `<span class="cond-field">${escapeHtml(fieldToName(c.field))}</span> <span class="cond-op">${escapeHtml(opText)}</span> <span class="cond-value">${escapeHtml(valText)}</span>`;
}

/**
 * 构建聚合条件的自然语言展示
 * 根据整个意图对象判断如何描述聚合查询
 * 例如："抗拉强度最大的前10条"、"抗拉强度的平均值"等
 */
function buildAggConditionHTML(c, sq) {
    const fieldName = fieldToName(c.field);
    const normalizedAgg = normalizeAggFunc(c.agg_func);
    const aggText = AGG_FUNC_MAP[normalizedAgg] || normalizedAgg;
    
    // 获取限制数量（limit）
    const limit = sq.limit || sq.target_limit;
    
    // 判断是否有排序方向与聚合一致（如 max + desc）
    const sortBy = sq.sort_by;
    const hasMatchingSort = sortBy && sortBy.field === c.field && (
        (normalizedAgg === 'max' && sortBy.order === 'desc') ||
        (normalizedAgg === 'min' && sortBy.order === 'asc')
    );
    
    // 判断该 group 中是否还有其他普通筛选条件（如"密度小于5的材料中弹性模量最小的"）
    let hasOtherFilter = false;
    if (sq.groups && sq.groups.length > 1) {
        hasOtherFilter = true;
    }
    
    // 构建自然语言描述
    let desc = '';
    
    if (limit && (hasMatchingSort || normalizedAgg === 'max' || normalizedAgg === 'min')) {
        // 有数量限制："抗拉强度最大的前10条"
        const directionText = normalizedAgg === 'max' ? '大' : '小';
        desc = `${escapeHtml(fieldName)}最${directionText}的前${limit}条`;
    } else if (normalizedAgg === 'max' || normalizedAgg === 'min') {
        // 无数量限制："抗拉强度最大的"
        const directionText = normalizedAgg === 'max' ? '大' : '小';
        desc = `${escapeHtml(fieldName)}最${directionText}的`;
    } else if (normalizedAgg === 'avg') {
        desc = `${escapeHtml(fieldName)}的平均值`;
    } else if (normalizedAgg === 'sum') {
        desc = `${escapeHtml(fieldName)}的总和`;
    } else if (normalizedAgg === 'count') {
        desc = `${escapeHtml(fieldName)}的计数`;
    } else if (normalizedAgg === 'variance') {
        desc = `${escapeHtml(fieldName)}的方差`;
    } else {
        // 兜底
        desc = `${escapeHtml(fieldName)}的${escapeHtml(aggText)}`;
    }
    
    return `<span class="cond-agg-natural">${desc}</span>`;
}

function buildReadableQueryHTML(sq) {
    const groups = sq.groups || [];
    if (groups.length === 0 && !sq.explanation) {
        return '';
    }

    const groupOp = sq.group_logic_op || 'and';
    const groupOpText = { and: '且', or: '或', not: '排除' }[groupOp] || '且';

    let html = '<div class="query-groups-container">';

    groups.forEach((g, idx) => {
        const conds = g.conditions || [];
        const datasets = g.datasets || [];
        const innerOp = g.logic_op || 'and';
        const innerOpText = { and: '且', or: '或', not: '排除' }[innerOp] || '且';

        // 组间连接符
        if (idx > 0) {
            html += `<div class="logic-connector"><span class="logic-op-badge">${groupOpText}</span></div>`;
        }

        html += '<div class="query-group-card">';

        // 数据集标签
        if (datasets.length > 0) {
            html += `<div class="group-datasets">${datasets.map(ds => `<span class="group-dataset-tag">${escapeHtml(ds)}</span>`).join('')}</div>`;
        }

        // 条件列表
        if (conds.length > 0) {
            html += '<div class="group-conditions">';
            conds.forEach((c, cidx) => {
                if (cidx > 0) {
                    html += `<div class="inner-logic-op"><span class="logic-op-badge small">${innerOpText}</span></div>`;
                }
                html += `<div class="condition-line">${conditionToReadableHTML(c, sq)}</div>`;
            });
            html += '</div>';
        } else if (datasets.length > 0) {
            html += '<div class="group-no-conditions">（无筛选条件，查询该数据集全部数据）</div>';
        }

        html += '</div>';
    });

    // 附加信息：排序、目标属性、查询类型
    const extras = [];
    if (sq.target_properties && sq.target_properties.length > 0) {
        const propNames = sq.target_properties.map(p => `<span class="cond-field">${escapeHtml(fieldToName(p))}</span>`).join('、');
        extras.push(`<span class="meta-label">查看属性</span>：${propNames}`);
    }
    if (sq.limit) {
        extras.push(`<span class="meta-label">数量限制</span>：前 ${sq.limit} 条`);
    }
    if (sq.intent_type === 'compare') {
        extras.push('<span class="meta-label">查询类型</span>：对比');
    }

    if (extras.length > 0) {
        html += `<div class="query-meta-line">${extras.join('　|　')}</div>`;
    }

    html += '</div>';
    return html;
}

// ==================== 卡片展示工具函数（提前定义避免提升问题） ====================
function toClassifiedFormat(wideRecords) {
    if (!wideRecords || wideRecords.length === 0) return [];
    return wideRecords.map(rec => {
        const obj = {};
        const op = {};
        const res = {};
        for (const [k, v] of Object.entries(rec)) {
            if (k === 'data_id' || k === 'title') continue;
            if (k.startsWith('object_')) {
                obj[k.slice(7)] = v;
            } else if (k.startsWith('operate_')) {
                op[k.slice(8)] = v;
            } else if (k.startsWith('result_')) {
                res[k.slice(7)] = v;
            } else {
                // 无前缀的列（新设计宽表），默认放入 object（与后端 to_classified_format 行为一致）
                obj[k] = v;
            }
        }
        return {
            data_id: rec.data_id,
            title: rec.title || '',
            object: obj,
            operate: op,
            result: res,
        };
    });
}

function formatPropsCell(props, excludeKeys, highlightProps) {
    if (!props || Object.keys(props).length === 0) return '-';
    const entries = Object.entries(props);
    const filtered = excludeKeys
        ? entries.filter(([k]) => !excludeKeys.includes(k))
        : entries;
    if (filtered.length === 0) return '-';
    const hpSet = highlightProps instanceof Set ? highlightProps : (Array.isArray(highlightProps) ? new Set(highlightProps) : new Set());
    return filtered
        .map(([k, v]) => {
            const isHighlight = hpSet.has(k);
            const cls = isHighlight ? 'prop-inline prop-inline-highlight' : 'prop-inline';
            return `<span class="${cls}"><span class="prop-inline-key">${escapeHtml(k)}</span><span class="prop-inline-sep">:</span><span class="prop-inline-val">${escapeHtml(v)}</span></span>`;
        })
        .join('');
}

/**
 * 以列表形式展示属性，每个属性占一行，键值区分更明显
 * 类似图二的清晰行列式展示
 */
function formatPropsList(props, highlightProps) {
    if (!props || Object.keys(props).length === 0) return '<span class="prop-empty">-</span>';
    const entries = Object.entries(props);
    if (entries.length === 0) return '<span class="prop-empty">-</span>';
    
    const hpSet = highlightProps instanceof Set ? highlightProps : (Array.isArray(highlightProps) ? new Set(highlightProps) : new Set());
    
    const items = entries.map(([k, v]) => {
        const isHighlight = hpSet.has(k);
        const highlightClass = isHighlight ? ' prop-item-highlight' : '';
        return `
            <div class="prop-item${highlightClass}">
                <span class="prop-item-key">${escapeHtml(k)}</span>
                <span class="prop-item-sep">:</span>
                <span class="prop-item-val">${escapeHtml(String(v))}</span>
            </div>
        `;
    });
    
    return `<div class="prop-list">${items.join('')}</div>`;
}

function showMoreResults(btn, currentLimit) {
    const wrapper = btn.closest('.result-table-wrapper');
    const newLimit = currentLimit + 10;
    const rows = wrapper.querySelectorAll('tbody tr');
    rows.forEach((row, idx) => {
        if (idx < newLimit) {
            row.classList.remove('hidden-row');
        }
    });
    const total = rows.length;
    if (newLimit >= total) {
        btn.remove();
    } else {
        btn.textContent = `点击显示更多（还有 ${total - newLimit} 条）`;
        btn.setAttribute('onclick', `showMoreResults(this, ${newLimit})`);
    }
}

function buildResultCardsHTML(records, highlightProps) {
    if (!records || records.length === 0) return '';

    const initialLimit = 10;
    const hpSet = highlightProps instanceof Set ? highlightProps : (Array.isArray(highlightProps) ? new Set(highlightProps) : new Set());

    let html = '<div class="result-table-wrapper">';
    html += '<table class="result-table">';
    html += '<thead><tr>';
    html += '<th class="th-dataid">data_id</th>';
    html += '<th class="th-object">对象型属性</th>';
    html += '<th class="th-operate">操作型属性</th>';
    html += '<th class="th-result">结果型属性</th>';
    html += '</tr></thead>';
    html += '<tbody>';

    records.forEach((rec, idx) => {
        const hiddenClass = idx >= initialLimit ? 'hidden-row' : '';
        const dataId = rec.data_id !== undefined ? rec.data_id : '-';
        html += `<tr class="${hiddenClass}">`;
        html += `<td class="col-dataid"><a href="javascript:void(0)" class="data-id-link" onclick="showDataDetail(${dataId})">${escapeHtml(String(dataId))}</a></td>`;
        html += `<td class="col-object">${formatPropsList(rec.object, hpSet)}</td>`;
        html += `<td class="col-operate">${formatPropsList(rec.operate, hpSet)}</td>`;
        html += `<td class="col-result">${formatPropsList(rec.result, hpSet)}</td>`;
        html += '</tr>';
    });

    html += '</tbody></table>';

    if (records.length > initialLimit) {
        html += `<button class="show-more-btn" onclick="showMoreResults(this, ${initialLimit})">点击显示更多（还有 ${records.length - initialLimit} 条）</button>`;
    }

    html += '</div>';
    return html;
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    initHistoryPanel();
    initInputBox();
    loadConversations();
});

// ==================== 历史记录面板 ====================
function initHistoryPanel() {
    const historyToggle = document.getElementById('historyToggle');
    const historyPanel = document.getElementById('historyPanel');
    const newChatBtn = document.getElementById('newChatBtn');
    const clearAllBtn = document.getElementById('clearAllBtn');

    if (historyToggle && historyPanel) {
        historyToggle.addEventListener('click', function() {
            historyPanel.classList.toggle('collapsed');
        });
    }

    if (newChatBtn) {
        newChatBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            createNewConversation();
        });
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            deleteAllConversations();
        });
    }
}

// ==================== 对话管理 ====================
async function loadConversations() {
    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/conversations`);
        const data = await resp.json();
        if (data.success) {
            conversations = data.conversations || [];
            renderHistoryList();
            // 不再自动切换到第一个对话，保持欢迎页让用户自主选择
            if (!currentConversationId && conversations.length === 0) {
                renderEmptyChat();
            }
        } else {
            console.error('加载对话列表失败:', data.error);
        }
    } catch (e) {
        console.error('加载对话列表异常:', e);
    }
}

async function createNewConversation() {
    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/empty`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await resp.json();
        if (data.success) {
            currentConversationId = data.data.conversation_id;
            conversations.unshift({
                conversation_id: data.data.conversation_id,
                title: data.data.title,
                latest_message: '',
                latest_timestamp: data.data.created_at,
                message_count: 0,
                query_hash: '',
            });
            renderHistoryList();
            renderEmptyChat();
            document.getElementById('userInput').focus();
        } else {
            console.error('创建空对话失败:', data.error);
            // 降级到旧逻辑
            currentConversationId = null;
            renderEmptyChat();
            renderHistoryList();
        }
    } catch (e) {
        console.error('创建空对话异常:', e);
        currentConversationId = null;
        renderEmptyChat();
        renderHistoryList();
    }
}

async function switchConversation(conversationId) {
    currentConversationId = conversationId;
    renderHistoryList();
    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/${conversationId}`);
        const data = await resp.json();
        if (data.success) {
            renderConversationDetail(data.data);
        } else {
            appendSystemMessage('加载对话详情失败：' + (data.error || '未知错误'));
        }
    } catch (e) {
        console.error('加载对话详情异常:', e);
        appendSystemMessage('网络异常，无法加载对话详情');
    }
}

async function deleteConversation(conversationId, event) {
    if (event) event.stopPropagation();
    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/${conversationId}`, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.success) {
            conversations = conversations.filter(c => c.conversation_id !== conversationId);
            if (currentConversationId === conversationId) {
                currentConversationId = null;
                if (conversations.length > 0) {
                    switchConversation(conversations[0].conversation_id);
                } else {
                    renderEmptyChat();
                }
            } else {
                renderHistoryList();
            }
        }
    } catch (e) {
        console.error('删除对话异常:', e);
    }
}

async function deleteAllConversations() {
    if (conversations.length === 0) {
        appendSystemMessage('当前没有对话记录');
        return;
    }
    if (!confirm('确定要清空所有对话记录吗？此操作不可恢复，且新对话 ID 将重新从 1 开始计数。')) {
        return;
    }
    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/clear`, {
            method: 'DELETE'
        });
        const data = await resp.json();
        if (data.success) {
            conversations = [];
            currentConversationId = null;
            renderHistoryList();
            renderEmptyChat();
            appendSystemMessage(data.message || '历史对话已清空');
        } else {
            appendSystemMessage('清空历史失败：' + (data.error || '未知错误'));
        }
    } catch (e) {
        console.error('清空所有对话异常:', e);
        appendSystemMessage('网络异常，无法清空历史对话');
    }
}

// ==================== 渲染 ====================
function renderHistoryList() {
    const historyList = document.getElementById('historyList');
    if (!historyList) return;

    historyList.innerHTML = '';

    if (conversations.length === 0) {
        historyList.innerHTML = '<div class="history-empty">暂无对话记录</div>';
        return;
    }

    conversations.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'history-item' + (conv.conversation_id === currentConversationId ? ' active' : '');
        item.onclick = () => switchConversation(conv.conversation_id);

        const timeStr = conv.latest_timestamp
            ? formatTime(conv.latest_timestamp)
            : '';

        item.innerHTML = `
            <div class="history-item-header">
                <span class="history-item-number">#${conv.conversation_id}</span>
                <button class="history-delete-btn" title="删除">×</button>
            </div>
            <div class="history-item-title">${escapeHtml(conv.title || '新对话')}</div>
            <div class="history-item-time">${escapeHtml(timeStr)} · ${conv.message_count || 0} 条消息</div>
        `;

        item.querySelector('.history-delete-btn').onclick = (e) => deleteConversation(conv.conversation_id, e);
        historyList.appendChild(item);
    });
}

function renderEmptyChat() {
    const chatHistory = document.getElementById('chatHistory');
    if (!chatHistory) return;
    chatHistory.innerHTML = `
        <div class="welcome-screen">
            <div class="welcome-icon">🔍</div>
            <div class="welcome-title">数据检索助手</div>
            <div class="welcome-desc">请输入你的问题，我将为你解析查询意图并生成结构化查询条件。</div>
            <div class="welcome-examples">
                <div class="welcome-example-title">你可以尝试：</div>
                <button class="welcome-example-chip" onclick="fillInput('查找抗拉强度大于500的钛合金')">查找抗拉强度大于500的钛合金</button>
                <button class="welcome-example-chip" onclick="fillInput('p型泽贝克系数 介于 179.5 和 179.6 之间的样本有哪些？')">p型泽贝克系数 介于 179.5 和 179.6 之间的样本有哪些？</button>
                <button class="welcome-example-chip" onclick="fillInput('请统计 p型电子热导率 的最大值。')">请统计 p型电子热导率 的最大值。</button>
                <button class="welcome-example-chip" onclick="fillInput('高铁材料服役大数据采集与计算-金属大气腐蚀中材料牌号为6005A的样本有哪些？')">高铁材料服役大数据采集与计算-金属大气腐蚀中材料牌号为6005A的样本有哪些？</button>
            </div>
        </div>
    `;
}

function fillInput(text) {
    const input = document.getElementById('userInput');
    if (input) {
        input.value = text;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 200) + 'px';
        input.focus();
    }
}

function renderConversationDetail(detail) {
    const chatHistory = document.getElementById('chatHistory');
    if (!chatHistory) return;

    chatHistory.innerHTML = '';

    // 系统欢迎语
    const welcome = document.createElement('div');
    welcome.className = 'message ai-message';
    welcome.innerHTML = `<div>你好，我是数据检索助手。请输入你的问题，我将为你解析查询意图并生成结构化查询条件。</div><div class="timestamp">系统就绪</div>`;
    chatHistory.appendChild(welcome);

    if (!detail.messages || detail.messages.length === 0) return;

    // 按时间顺序渲染消息
    detail.messages.forEach(msg => {
        if (msg.role === 'user') {
            appendUserMessageToDOM(msg.content, msg.created_at);
        } else if (msg.role === 'assistant') {
            if (msg.message_type === 'intent_query') {
                // 首条意图查询结果：展示意图解析面板 + 卡片
                const meta = msg.meta || {};
                appendIntentResultToDOM({
                    original_query: detail.title || '',
                    parsed_intent: detail.structured_query || {},
                    structured_query: detail.structured_query || {},
                    from_cache: meta.from_cache,
                    results: meta.results,
                    classified_results: meta.classified_results,
                    total: meta.total,
                    sql: meta.sql,
                    sql_params: meta.sql_params,
                    sql_rendered: meta.sql_rendered,
                }, msg.created_at);
            } else if (msg.message_type === 'follow_up') {
                const meta = msg.meta || {};
                appendFollowUpResultToDOM({
                    answer: msg.content,
                    results: meta.results,
                    classified_results: meta.classified_results,
                    total: meta.total,
                    sql: meta.sql,
                    params: meta.params,
                    intent: meta.intent,
                    chart_data: meta.chart_data,
                    analysis_result: meta.analysis_result,
                }, msg.created_at);
            } else {
                appendAIMessageToDOM(msg.content, msg.created_at);
            }
        }
    });

    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendUserMessageToDOM(text, timestamp) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message user-message';
    div.innerHTML = `<div>${escapeHtml(text)}</div><div class="timestamp">${formatTime(timestamp)}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendAIMessageToDOM(text, timestamp) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `<div>${escapeHtml(text)}</div><div class="timestamp">${formatTime(timestamp)}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendFollowUpAnswerToDOM(text) {
    // 兼容旧调用：纯文本
    appendFollowUpResultToDOM({ answer: text });
}

function getHighlightProps(intentOrSq) {
    const sq = intentOrSq || {};
    let props = sq.target_properties || [];
    // 若 LLM 未填充 target_properties，则从查询条件的 field 中提取作为回退
    if (props.length === 0 && sq.groups && Array.isArray(sq.groups)) {
        const fields = new Set();
        sq.groups.forEach(g => {
            if (g.conditions && Array.isArray(g.conditions)) {
                g.conditions.forEach(c => {
                    if (c.field) fields.add(c.field);
                });
            }
        });
        props = Array.from(fields);
    }
    // 兼容旧版 intent 结构（conditions / conditions1 在顶层）
    if (props.length === 0 && sq.conditions && Array.isArray(sq.conditions)) {
        const fields = new Set();
        sq.conditions.forEach(c => {
            if (typeof c === 'object' && c.field) fields.add(c.field);
        });
        props = Array.from(fields);
    }
    if (props.length === 0 && sq.conditions1 && Array.isArray(sq.conditions1)) {
        const fields = new Set();
        sq.conditions1.forEach(c => {
            if (typeof c === 'object' && c.field) fields.add(c.field);
        });
        props = Array.from(fields);
    }
    return props;
}

function buildStatTableHTML(chartData) {
    if (!chartData || !chartData.data) return '';
    const columns = chartData.data.columns || [];
    const rows = chartData.data.rows || [];
    if (!columns.length || !rows.length) return '';

    let html = '<div class="stat-table-wrapper" style="margin:12px 0;">';
    if (chartData.title) {
        html += `<div style="font-weight:600;color:#2196f3;margin-bottom:8px;font-size:14px;">${escapeHtml(chartData.title)}</div>`;
    }
    html += '<table class="data-table">';
    html += '<thead><tr>' + columns.map(c => `<th>${escapeHtml(c.header || c.field)}</th>`).join('') + '</tr></thead>';
    html += '<tbody>';
    for (const row of rows) {
        html += '<tr>' + columns.map(c => `<td>${escapeHtml(String(row[c.field] !== undefined ? row[c.field] : ''))}</td>`).join('') + '</tr>';
    }
    html += '</tbody></table>';
    html += '</div>';
    return html;
}

function renderChart(chartData, containerId) {
    console.log('[renderChart] chart_type=', chartData ? chartData.chart_type : null, 'echarts_loaded=', !!window.echarts);
    if (!chartData) {
        console.warn('[renderChart] chartData is null/undefined');
        return;
    }
    if (!window.echarts) {
        console.warn('[renderChart] ECharts not loaded, cannot render chart');
        return;
    }
    const container = document.getElementById(containerId);
    if (!container) {
        console.warn('[renderChart] container not found:', containerId);
        return;
    }

    try {
        const chart = echarts.init(container);
        let option = {};

        if (chartData.chart_type === 'pie') {
            const details = (chartData.data && chartData.data.details) || [];
            const dataCount = details.length;
            // 当类别过多时，关闭直接标签，避免重叠；只保留 tooltip 和图例
            const showLabels = dataCount <= 15;
            option = {
                title: { text: chartData.title || '', left: 'center', textStyle: { fontSize: 14 } },
                tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
                legend: {
                    type: 'scroll',
                    orient: 'horizontal',
                    bottom: '0%',
                    left: 'center',
                    height: 60,
                    pageIconColor: '#2196f3',
                    pageTextStyle: { color: '#666' }
                },
                series: [{
                    type: 'pie',
                    radius: ['35%', '58%'],
                    center: ['50%', '46%'],
                    avoidLabelOverlap: true,
                    itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
                    label: {
                        show: showLabels,
                        position: 'outside',
                        formatter: '{b}\n{d}%',
                        minMargin: 5,
                        edgeDistance: 10,
                        lineHeight: 15
                    },
                    labelLine: {
                        show: showLabels,
                        length: 12,
                        length2: 8,
                        smooth: true
                    },
                    emphasis: {
                        label: { show: true, fontSize: 14, fontWeight: 'bold' },
                        itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
                    },
                    data: details.map(d => ({ name: d.name, value: d.value }))
                }]
            };
        } else if (chartData.chart_type === 'bar') {
            const categories = (chartData.data && chartData.data.categories) || [];
            const seriesData = (chartData.data && chartData.data.series && chartData.data.series[0] && chartData.data.series[0].data) || [];
            option = {
                title: { text: chartData.title || '', left: 'center', textStyle: { fontSize: 14 } },
                tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
                grid: { left: '3%', right: '4%', bottom: '15%', top: '15%', containLabel: true },
                xAxis: { type: 'category', data: categories, axisLabel: { rotate: 30, fontSize: 11 } },
                yAxis: { type: 'value', name: '数量' },
                series: [{
                    data: seriesData,
                    type: 'bar',
                    name: (chartData.data && chartData.data.series && chartData.data.series[0] && chartData.data.series[0].name) || '数量',
                    itemStyle: { color: '#5470c6', borderRadius: [4, 4, 0, 0] }
                }]
            };
        } else if (chartData.chart_type === 'line') {
            const xAxis = (chartData.data && chartData.data.x_axis) || [];
            const seriesData = (chartData.data && chartData.data.series && chartData.data.series[0] && chartData.data.series[0].data) || [];
            const yField = (chartData.data && chartData.data.y_field) || '';
            option = {
                title: { text: chartData.title || '', left: 'center', textStyle: { fontSize: 14 } },
                tooltip: { trigger: 'axis', formatter: function(params) {
                    const p = params[0];
                    return `${p.name}<br/>${p.seriesName}: ${p.value}`;
                }},
                grid: { left: '3%', right: '4%', bottom: '15%', top: '15%', containLabel: true },
                xAxis: { type: 'category', data: xAxis, axisLabel: { rotate: 30, fontSize: 11 }, name: chartData.data.x_field || '' },
                yAxis: { type: 'value', name: yField },
                series: [{
                    data: seriesData,
                    type: 'line',
                    smooth: true,
                    name: yField,
                    itemStyle: { color: '#5470c6' },
                    lineStyle: { width: 2 },
                    areaStyle: { color: 'rgba(84, 112, 198, 0.1)' },
                    symbol: 'circle',
                    symbolSize: 6
                }]
            };
        } else {
            chart.dispose();
            return;
        }

        chart.setOption(option);
        console.log('[renderChart] chart rendered successfully for', chartData.chart_type);
    } catch (err) {
        console.error('[renderChart] ECharts render failed:', err);
    }
}

function appendFollowUpResultToDOM(data, timestamp) {
    console.log('[appendFollowUpResultToDOM] chart_data=', data.chart_data);
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';

    let html = buildFollowUpResultHTML(data);

    // 追加图表或统计表格（pie / bar / table）
    let chartId = null;
    if (data.chart_data && data.chart_data.chart_type) {
        if (data.chart_data.chart_type === 'table') {
            html += buildStatTableHTML(data.chart_data);
        } else {
            chartId = 'chart-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
            html += `<div id="${chartId}" style="width:100%;height:320px;margin:12px 0;"></div>`;
        }
    }

    const classified = data.classified_results || toClassifiedFormat(data.results);
    if (classified && classified.length > 0) {
        const highlightProps = getHighlightProps(data.intent);
        html += buildResultCardsHTML(classified, highlightProps);
    }
    div.innerHTML = html + `<div class="timestamp">${formatTime(timestamp)}</div>`;

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    // 渲染图表（DOM 已插入）
    if (chartId && data.chart_data) {
        renderChart(data.chart_data, chartId);
    }
}

function appendSystemMessage(text) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `<div class="error-box">${escapeHtml(text)}</div><div class="timestamp">${formatTime()}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendLoadingMessage() {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message loading';
    div.id = 'loadingMessage';
    div.innerHTML = `<div class="loading-text">处理中...</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return div;
}

function removeLoadingMessage() {
    const loading = document.getElementById('loadingMessage');
    if (loading) loading.remove();
}

function appendErrorToDOM(text) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';
    div.innerHTML = `<div class="error-box">${escapeHtml(text)}</div><div class="timestamp">${formatTime()}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// ==================== 意图结果 HTML 构建 ====================
function appendIntentResultToDOM(data, timestamp) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';

    // 使用分类格式展示卡片，如果没有则降级为意图解析面板
    let html = buildIntentResultHTML(data);
    const classified = data.classified_results || toClassifiedFormat(data.results);
    if (classified && classified.length > 0) {
        const highlightProps = getHighlightProps(data.structured_query || data.parsed_intent);
        html += buildResultCardsHTML(classified, highlightProps);
    }
    div.innerHTML = html;

    const timestampDiv = document.createElement('div');
    timestampDiv.className = 'timestamp';
    timestampDiv.textContent = formatTime(timestamp);
    div.appendChild(timestampDiv);

    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    div.querySelectorAll('pre code').forEach(block => {
        if (window.hljs) hljs.highlightElement(block);
    });
}

function buildIntentResultHTML(data) {
    const intent = data.parsed_intent || data.structured_query || {};
    const sq = data.structured_query || intent || {};

    let html = '<div class="intent-result compact">';

    // 原始查询（突出显示）
    html += `
        <div class="intent-section compact-section">
            <div class="intent-section-title">原始查询</div>
            <div class="intent-section-content query-text">${escapeHtml(data.original_query || '')}</div>
        </div>
    `;

    // 查询概览：缓存状态 + 结果数量（一行紧凑排列）
    let overviewBadges = '';

    if (data.hasOwnProperty('from_cache')) {
        overviewBadges += `<span class="intent-badge ${data.from_cache ? 'green' : 'orange'}">${data.from_cache ? '缓存命中' : '实时查询'}</span>`;
    }

    if (data.total !== undefined) {
        overviewBadges += `<span class="intent-badge purple">${data.total} 条</span>`;
    }

    if (overviewBadges) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">查询概览</div>
                <div class="intent-section-content overview-badges">${overviewBadges}</div>
            </div>
        `;
    }

    // 实体 + 目标属性（紧凑合并为一行）
    const hasEntities = intent.entities && intent.entities.length > 0;
    const hasProps = intent.target_properties && intent.target_properties.length > 0;
    if (hasEntities || hasProps) {
        let tags = '';
        if (hasEntities) {
            tags += intent.entities.map(e => `<span class="intent-badge orange">${escapeHtml(e)}</span>`).join('');
        }
        if (hasProps) {
            tags += intent.target_properties.map(p => `<span class="intent-badge purple">${escapeHtml(p)}</span>`).join('');
        }
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">实体 / 属性</div>
                <div class="intent-section-content overview-badges">${tags}</div>
            </div>
        `;
    }

    // 数据集
    const datasets = intent.datasets1 || intent.datasets || [];
    if (datasets.length > 0) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">关联数据集</div>
                <div class="intent-section-content overview-badges">
                    ${datasets.map(ds => `<span class="intent-badge">${escapeHtml(ds)}</span>`).join('')}
                </div>
            </div>
        `;
    }

    // 结构化查询（可读化卡片 + 原始JSON折叠）
    const readableHTML = buildReadableQueryHTML(sq);
    if (readableHTML) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">查询条件</div>
                ${readableHTML}
            </div>
        `;
    }

    // 结构化查询对象（可折叠）：包含查询条件（JSON）和查询语句（SQL）
    html += `
        <div class="intent-section compact-section">
            <details class="json-details">
                <summary class="json-summary">
                    <span class="json-summary-title">结构化查询对象</span>
                    <span class="json-summary-hint">点击展开</span>
                </summary>
                <div style="padding: 12px;">
                    <div class="intent-section-title" style="margin-bottom: 6px;">查询条件（JSON接口形式）</div>
                    <pre class="json-block compact-json" style="margin-bottom: 12px;"><code class="language-json">${escapeHtml(JSON.stringify(sq, null, 2))}</code></pre>
                    ${data.sql ? `<div class="intent-section-title" style="margin-bottom: 6px;">查询语句（SQL形式）</div>
                    <pre class="json-block compact-json"><code class="language-sql">${escapeHtml(data.sql)}</code></pre>` : ''}
                </div>
            </details>
        </div>
    `;

    html += '</div>';
    return html;
}

function buildFollowUpResultHTML(data) {
    const intent = data.intent || {};
    const sq = intent || {};

    let html = '<div class="intent-result compact">';

    // 原始查询
    html += `
        <div class="intent-section compact-section">
            <div class="intent-section-title">原始查询</div>
            <div class="intent-section-content query-text">${escapeHtml(data.original_query || '')}</div>
        </div>
    `;

    // 数据来源
    const scopeText = data.scope === 'original' ? '基于初表（首轮结果）' : '基于上一轮对话结果';
    const scopeClass = data.scope === 'original' ? 'orange' : 'green';
    html += `
        <div class="intent-section compact-section">
            <div class="intent-section-title">数据来源</div>
            <div class="intent-section-content overview-badges">
                <span class="intent-badge ${scopeClass}">${escapeHtml(scopeText)}</span>
            </div>
        </div>
    `;

    // 查询概览：结果数量
    let overviewBadges = '';

    if (data.hasOwnProperty('total')) {
        overviewBadges += `<span class="intent-badge purple">${data.total} 条</span>`;
    }

    if (overviewBadges) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">查询概览</div>
                <div class="intent-section-content overview-badges">${overviewBadges}</div>
            </div>
        `;
    }

    // 实体 + 目标属性
    const hasEntities = intent.entities && intent.entities.length > 0;
    const hasProps = intent.target_properties && intent.target_properties.length > 0;
    if (hasEntities || hasProps) {
        let tags = '';
        if (hasEntities) {
            tags += intent.entities.map(e => `<span class="intent-badge orange">${escapeHtml(e)}</span>`).join('');
        }
        if (hasProps) {
            tags += intent.target_properties.map(p => `<span class="intent-badge purple">${escapeHtml(p)}</span>`).join('');
        }
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">实体 / 属性</div>
                <div class="intent-section-content overview-badges">${tags}</div>
            </div>
        `;
    }

    // 关联数据集
    const datasets = intent.datasets1 || intent.datasets || [];
    if (datasets.length > 0) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">关联数据集</div>
                <div class="intent-section-content overview-badges">
                    ${datasets.map(ds => `<span class="intent-badge">${escapeHtml(ds)}</span>`).join('')}
                </div>
            </div>
        `;
    }

    // 查询条件（可读化卡片 + 原始JSON折叠）
    const readableHTML = buildReadableQueryHTML(sq);
    if (readableHTML) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">查询条件</div>
                ${readableHTML}
            </div>
        `;
    }

    // SQL 详情（可折叠）
    if (data.sql) {
        html += buildSQLDetailsHTML(data.sql, data.params);
    }

    // 结构化查询对象（可折叠）：包含查询条件（JSON）和查询语句（SQL）
    if (Object.keys(sq).length > 0) {
        html += `
            <div class="intent-section compact-section">
                <details class="json-details">
                    <summary class="json-summary">
                        <span class="json-summary-title">结构化查询对象</span>
                        <span class="json-summary-hint">点击展开</span>
                    </summary>
                    <div style="padding: 12px;">
                        <div class="intent-section-title" style="margin-bottom: 6px;">查询条件（JSON接口形式）</div>
                        <pre class="json-block compact-json" style="margin-bottom: 12px;"><code class="language-json">${escapeHtml(JSON.stringify(sq, null, 2))}</code></pre>
                        ${data.sql ? `<div class="intent-section-title" style="margin-bottom: 6px;">查询语句（SQL形式）</div>
                        <pre class="json-block compact-json"><code class="language-sql">${escapeHtml(data.sql)}</code></pre>` : ''}
                    </div>
                </details>
            </div>
        `;
    }

    html += '</div>';
    return html;
}

function buildSQLDetailsHTML(sql, params) {
    let paramStr = '';
    if (params && params.length > 0) {
        paramStr = `<div class="sql-params">参数: ${escapeHtml(JSON.stringify(params))}</div>`;
    }
    return `
        <details class="details-block sql-details">
            <summary>执行的 SQL</summary>
            <pre class="json-block" style="margin-top:6px;"><code class="language-sql">${escapeHtml(sql)}</code></pre>
            ${paramStr}
        </details>
    `;
}

function buildFollowUpIntentHTML(intent) {
    const conditions = intent.conditions1 || intent.conditions || [];
    const hasContent = intent.intent_type || conditions.length > 0 ||
                       (intent.entities && intent.entities.length > 0) ||
                       (intent.target_properties && intent.target_properties.length > 0);
    if (!hasContent) return '';

    let html = '<details class="details-block intent-details">';
    html += '<summary>意图解析</summary>';
    html += '<div style="margin-top:8px;">';

    if (intent.intent_type) {
        const intentTypeMap = { search: '检索', compare: '对比' };
        html += `<span class="intent-badge">${escapeHtml(intentTypeMap[intent.intent_type] || intent.intent_type)}</span>`;
    }

    if (intent.entities && intent.entities.length > 0) {
        html += intent.entities.map(e => `<span class="intent-badge orange">${escapeHtml(e)}</span>`).join('');
    }

    if (intent.target_properties && intent.target_properties.length > 0) {
        html += intent.target_properties.map(p => `<span class="intent-badge purple">${escapeHtml(p)}</span>`).join('');
    }

    if (conditions.length > 0) {
        html += '<ul class="condition-list" style="margin-top:8px;">';
        conditions.forEach(c => {
            if (typeof c === 'string') {
                html += `<li class="logic-op">${escapeHtml(c.toUpperCase())}</li>`;
            } else {
                html += `<li>${escapeHtml(c.field)} ${escapeHtml(c.operator)} ${escapeHtml(String(c.value))}${c.unit ? ' ' + escapeHtml(c.unit) : ''}</li>`;
            }
        });
        html += '</ul>';
    }

    const logicOp = intent.group_logic_op || intent.logic_op;
    if (logicOp) {
        html += `<span class="intent-badge green">${escapeHtml(logicOp)}</span>`;
    }

    html += '</div></details>';
    return html;
}

function buildDataTableHTML(records, options) {
    const opts = options || {};
    const maxRows = opts.maxRows || 10;
    const maxCols = opts.maxCols || 6;

    if (!records || records.length === 0) return '';

    // 选择展示列：优先 data_id / title，再补充其他字段
    const first = records[0];
    const priority = ['data_id', 'title'];
    const cols = [];
    for (const c of priority) {
        if (c in first) cols.push(c);
    }
    for (const c of Object.keys(first)) {
        if (cols.length >= maxCols) break;
        if (!cols.includes(c)) cols.push(c);
    }

    const displayRecords = records.slice(0, maxRows);
    const hasMore = records.length > maxRows;

    let html = '<div class="intent-section">';
    html += '<div class="intent-section-title">数据预览</div>';
    html += '<div class="data-table-wrapper">';
    html += '<table class="data-table">';
    html += '<thead><tr>' + cols.map(c => `<th>${escapeHtml(c)}</th>`).join('') + '</tr></thead>';
    html += '<tbody>';
    for (const row of displayRecords) {
        html += '<tr>' + cols.map(c => `<td>${escapeHtml(String(row[c] !== undefined ? row[c] : ''))}</td>`).join('') + '</tr>';
    }
    html += '</tbody></table>';
    html += '</div>'; // data-table-wrapper
    if (hasMore) {
        html += `<div class="data-table-caption">还有 ${records.length - maxRows} 条数据未展示</div>`;
    }
    html += '</div>'; // intent-section
    return html;
}

// ==================== 模式切换 ====================
function switchMode(mode) {
    currentMode = mode;
    document.getElementById('modeIntent').classList.toggle('active', mode === 'intent');
    document.getElementById('modeGraph').classList.toggle('active', mode === 'graph');

    const input = document.getElementById('userInput');
    const chatHistory = document.getElementById('chatHistory');

    if (mode === 'graph') {
        input.placeholder = 'Enter your knowledge graph question (e.g., Which specific category does hybrid laminated composite directly belong to?)';
        // 清空对话，显示知识问答欢迎页
        chatHistory.innerHTML = `
            <div class="welcome-screen">
                <div class="welcome-icon">🌐</div>
                <div class="welcome-title">知识问答助手</div>
                <div class="welcome-desc">Powered by materials science knowledge graph, answering questions about entity relationships, classification hierarchies, and property associations.</div>
                <div class="welcome-examples">
                    <div class="welcome-example-title">You can try:</div>
                    <button class="welcome-example-chip" onclick="fillInput('Which specific category does hybrid laminated composite directly belong to?')">Which specific category does hybrid laminated composite directly belong to?</button>
                    <button class="welcome-example-chip" onclick="fillInput('In the structural composition of hybrid laminated composite, what kind of connection or interaction relationship exists between it and matrix?')">In the structural composition of hybrid laminated composite, what kind of connection or interaction relationship exists between it and matrix?</button>
                </div>
            </div>
        `;
    } else {
        input.placeholder = '请输入你的问题...';
        renderEmptyChat();
    }
}

// ==================== 知识问答结果渲染 ====================
function appendKGQAResultToDOM(data, timestamp) {
    const chatHistory = document.getElementById('chatHistory');
    const div = document.createElement('div');
    div.className = 'message ai-message';

    let html = '<div class="intent-result compact">';

    // 原始问题
    html += `
        <div class="intent-section compact-section">
            <div class="intent-section-title">问题</div>
            <div class="intent-section-content query-text">${escapeHtml(data.question || '')}</div>
        </div>
    `;

    // 实体链接结果
    if (data.linked_entities && data.linked_entities.length > 0) {
        html += `
            <div class="intent-section compact-section">
                <div class="intent-section-title">链接实体</div>
                <div class="intent-section-content overview-badges">
                    ${data.linked_entities.map(e => `<span class="intent-badge orange">${escapeHtml(e)}</span>`).join('')}
                </div>
            </div>
        `;
    }

    // 答案
    html += `
        <div class="intent-section compact-section">
            <div class="intent-section-title">答案</div>
            <div class="intent-section-content" style="font-weight:600;color:#1565c0;">${escapeHtml(data.answer || '')}</div>
        </div>
    `;

    // 检索上下文（可折叠）
    if (data.retrieved_context) {
        html += `
            <details class="json-details" style="margin-top:8px;">
                <summary><span class="json-summary-title">检索上下文</span><span class="json-summary-hint">点击展开</span></summary>
                <pre class="json-block compact-json"><code>${escapeHtml(data.retrieved_context)}</code></pre>
            </details>
        `;
    }

    html += '</div>';

    div.innerHTML = html + `<div class="timestamp">${formatTime(timestamp)}</div>`;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// ==================== 发送消息 ====================
async function sendMessage() {
    const input = document.getElementById('userInput');
    const message = input.value.trim();
    if (!message) return;

    // ===== 知识问答模式 =====
    if (currentMode === 'graph') {
        setInputDisabled(true);
        appendUserMessageToDOM(message);
        input.value = '';
        input.style.height = 'auto';
        const loading = appendLoadingMessage();

        try {
            const resp = await fetch(`${API_BASE_URL}/api/graph/kgqa`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: message })
            });
            const data = await resp.json();
            removeLoadingMessage();

            if (data.success) {
                appendKGQAResultToDOM(data.data);
            } else {
                appendErrorToDOM(data.error || '知识问答失败');
            }
        } catch (error) {
            removeLoadingMessage();
            appendErrorToDOM(error.message || '网络请求失败');
        } finally {
            setInputDisabled(false);
        }
        return;
    }

    // ===== 数据检索模式（原有逻辑） =====
    setInputDisabled(true);
    appendUserMessageToDOM(message);
    input.value = '';
    input.style.height = 'auto';

    const loading = appendLoadingMessage();

    try {
        let data;
        const currentConv = conversations.find(c => c.conversation_id === currentConversationId);
        const isEmptyConv = !currentConv || (currentConv.message_count || 0) === 0;
        if (!currentConversationId) {
            // 降级：未创建空对话时，走旧接口
            const resp = await fetch(`${API_BASE_URL}/api/chat/conversations`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: message })
            });
            data = await resp.json();
            removeLoadingMessage();

            if (data.success) {
                currentConversationId = data.data.conversation_id;
                conversations.unshift({
                    conversation_id: data.data.conversation_id,
                    title: data.data.title,
                    latest_message: data.data.title,
                    latest_timestamp: new Date().toISOString(),
                    message_count: 2,
                    query_hash: '',
                });
                renderHistoryList();
                appendIntentResultToDOM(data.data);
            } else {
                appendErrorToDOM(data.error || '创建对话失败');
            }
        } else if (isEmptyConv) {
            // 空对话的首次数据检索
            const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/${currentConversationId}/init`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: message })
            });
            data = await resp.json();
            removeLoadingMessage();

            if (data.success) {
                if (currentConv) {
                    currentConv.title = data.data.title;
                    currentConv.message_count = 2;
                    currentConv.latest_message = data.data.title;
                    currentConv.latest_timestamp = new Date().toISOString();
                }
                renderHistoryList();
                appendIntentResultToDOM(data.data);
            } else {
                appendErrorToDOM(data.error || '数据检索失败');
            }
        } else {
            // 在已有对话中追加后续问答
            const resp = await fetch(`${API_BASE_URL}/api/chat/conversations/${currentConversationId}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: message })
            });
            data = await resp.json();
            removeLoadingMessage();

            if (data.success) {
                console.log('[sendMessage] follow-up response:', data.data);
                if (data.data.structured_query) {
                    // 保险触发：后端降级为数据检索
                    appendIntentResultToDOM(data.data);
                } else {
                    appendFollowUpResultToDOM({
                        answer: data.data.answer,
                        results: data.data.results,
                        classified_results: data.data.classified_results,
                        total: data.data.total,
                        sql: data.data.sql,
                        params: data.data.params,
                        intent: data.data.intent,
                        chart_data: data.data.chart_data,
                        analysis_result: data.data.analysis_result,
                        scope: data.data.scope,
                        original_query: data.data.original_query,
                    });
                }
                // 更新列表中的最新消息
                if (currentConv) {
                    currentConv.latest_message = message;
                    currentConv.message_count = (currentConv.message_count || 0) + 2;
                    currentConv.latest_timestamp = new Date().toISOString();
                }
                renderHistoryList();
            } else {
                appendErrorToDOM(data.error || '发送消息失败');
            }
        }
    } catch (error) {
        removeLoadingMessage();
        appendErrorToDOM(error.message || '网络请求失败');
    } finally {
        setInputDisabled(false);
    }
}

// ==================== 输入框交互 ====================
function initInputBox() {
    const userInput = document.getElementById('userInput');
    if (!userInput) return;

    userInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    userInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 200) + 'px';
    });
}

// ==================== 工具函数 ====================
function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function formatTime(isoString) {
    const d = isoString ? new Date(isoString) : new Date();
    if (isNaN(d.getTime())) return '';
    return d.toLocaleString('zh-CN', {
        month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
}

function setInputDisabled(disabled) {
    const input = document.getElementById('userInput');
    const sendBtn = document.querySelector('.send-button');
    if (input) {
        input.disabled = disabled;
    }
    if (sendBtn) {
        sendBtn.disabled = disabled;
    }
}

// ==================== 数据详情弹窗 ====================

async function showDataDetail(dataId) {
    const modal = document.getElementById('dataDetailModal');
    const body = document.getElementById('dataDetailBody');
    const title = document.getElementById('dataDetailTitle');

    title.textContent = `(data_id: ${dataId})`;
    body.innerHTML = '<div class="loading-text">加载中...</div>';
    modal.classList.add('show');

    try {
        const resp = await fetch(`${API_BASE_URL}/api/chat/data_detail/${dataId}`);
        const result = await resp.json();
        if (result.success && result.data) {
            body.innerHTML = buildDataDetailHTML(result.data);
            // 渲染元素组成饼图（如果有）
            if (result.data.element_composition && result.data.element_composition.has_composition) {
                renderElementCompositionChart(result.data.element_composition);
            }
        } else {
            body.innerHTML = `<div class="error-box">${escapeHtml(result.error || '加载失败')}</div>`;
        }
    } catch (e) {
        body.innerHTML = `<div class="error-box">网络异常，无法加载数据详情</div>`;
        console.error('加载数据详情异常:', e);
    }
}

function closeDataDetailModal() {
    const modal = document.getElementById('dataDetailModal');
    modal.classList.remove('show');
}

function buildDataDetailHTML(data) {
    let html = '<div class="data-detail-content">';

    // 标题
    html += `<div class="data-detail-title">${escapeHtml(data.title || '未命名')}</div>`;

    // 数据来源
    if (data.dataset_source) {
        html += '<div class="data-detail-section data-source-section">';
        html += '<div class="data-detail-section-title">数据来源</div>';
        html += '<div class="data-detail-props">';
        html += `<div class="data-detail-prop"><span class="prop-name">所属数据集</span><span class="prop-value">${escapeHtml(data.dataset_source)}</span></div>`;
        html += '</div></div>';
    }

    // 元素组成饼图（如果有）
    if (data.element_composition && data.element_composition.has_composition) {
        html += '<div class="element-composition-section">';
        html += '<div class="data-detail-section-title">元素组成</div>';
        html += `<div id="element-chart-${data.data_id}" class="element-chart-container"></div>`;
        html += '</div>';
    }

    // 对象属性
    if (data.object && Object.keys(data.object).length > 0) {
        html += '<div class="data-detail-section"><div class="data-detail-section-title">对象属性</div>';
        html += '<div class="data-detail-props">';
        for (const [k, v] of Object.entries(data.object)) {
            html += `<div class="data-detail-prop"><span class="prop-name">${escapeHtml(k)}</span><span class="prop-value">${escapeHtml(String(v))}</span></div>`;
        }
        html += '</div></div>';
    }

    // 操作属性
    if (data.operate && Object.keys(data.operate).length > 0) {
        html += '<div class="data-detail-section"><div class="data-detail-section-title">操作属性</div>';
        html += '<div class="data-detail-props">';
        for (const [k, v] of Object.entries(data.operate)) {
            html += `<div class="data-detail-prop"><span class="prop-name">${escapeHtml(k)}</span><span class="prop-value">${escapeHtml(String(v))}</span></div>`;
        }
        html += '</div></div>';
    }

    // 结果属性
    if (data.result && Object.keys(data.result).length > 0) {
        html += '<div class="data-detail-section"><div class="data-detail-section-title">结果属性</div>';
        html += '<div class="data-detail-props">';
        for (const [k, v] of Object.entries(data.result)) {
            html += `<div class="data-detail-prop"><span class="prop-name">${escapeHtml(k)}</span><span class="prop-value">${escapeHtml(String(v))}</span></div>`;
        }
        html += '</div></div>';
    }

    html += '</div>';
    return html;
}

/**
 * 渲染元素组成饼图
 */
function renderElementCompositionChart(composition) {
    if (!window.echarts) {
        console.warn('[renderElementCompositionChart] ECharts not loaded');
        return;
    }

    const elements = composition.elements || [];
    if (elements.length === 0) return;

    // 查找图表容器（使用第一个找到的）
    const container = document.querySelector('.element-chart-container');
    if (!container) return;

    try {
        const chart = echarts.init(container);

        // 元素配色方案（周期表风格）
        const colorPalette = [
            '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
            '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#ff9f7f',
            '#ffdb5c', '#67e0e3', '#37a2da', '#32c5e9', '#9fe6b8',
            '#ff9f7f', '#fb7293', '#e062ae', '#e690d1', '#e7bcf3'
        ];

        const dataCount = elements.length;
        const showLabels = dataCount <= 12;

        const option = {
            title: {
                text: '元素质量分数（wt%）',
                left: 'center',
                top: '2%',
                textStyle: { fontSize: 13, color: '#666' }
            },
            tooltip: {
                trigger: 'item',
                formatter: function(params) {
                    return `<b>${params.name}</b><br/>含量: ${params.value}%<br/>占比: ${params.percent}%`;
                }
            },
            legend: {
                type: 'scroll',
                orient: 'horizontal',
                bottom: '2%',
                left: 'center',
                itemWidth: 12,
                itemHeight: 12,
                textStyle: { fontSize: 11 }
            },
            color: colorPalette,
            series: [{
                type: 'pie',
                radius: ['30%', '55%'],
                center: ['50%', '48%'],
                avoidLabelOverlap: true,
                itemStyle: {
                    borderRadius: 4,
                    borderColor: '#fff',
                    borderWidth: 2
                },
                label: {
                    show: showLabels,
                    position: 'outside',
                    formatter: '{b}\n{c}%',
                    fontSize: 11
                },
                labelLine: {
                    show: showLabels,
                    length: 10,
                    length2: 6
                },
                emphasis: {
                    label: { show: true, fontSize: 13, fontWeight: 'bold' },
                    itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
                },
                data: elements.map(e => ({
                    name: e.name,
                    value: e.value,
                    raw: e.raw
                }))
            }]
        };

        chart.setOption(option);
        console.log('[renderElementCompositionChart] chart rendered with', elements.length, 'elements');
    } catch (err) {
        console.error('[renderElementCompositionChart] failed:', err);
    }
}

// 点击弹窗背景关闭
document.addEventListener('click', function(e) {
    const modal = document.getElementById('dataDetailModal');
    if (modal && e.target === modal) {
        closeDataDetailModal();
    }
});
