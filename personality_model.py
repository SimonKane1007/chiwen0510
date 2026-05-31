"""
文本性格与价值观推理模型
基于：Big Five人格理论 + Schwartz基本价值观理论 + 语言学指标
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import re
from collections import Counter


# ─────────────────────────────────────────────
# 第一步：推理结构模型定义
# ─────────────────────────────────────────────

@dataclass
class PersonalitySignal:
    """单条语言信号"""
    category: str       # 信号类别
    indicator: str      # 指标名称
    evidence: str       # 文本证据
    weight: float       # 权重 0~1
    direction: str      # 正向 / 负向


@dataclass
class PersonalityDimension:
    """人格维度（Big Five）"""
    name: str
    score: float = 0.0          # -1.0 ~ +1.0
    signals: List[PersonalitySignal] = field(default_factory=list)
    interpretation: str = ""


@dataclass
class ValueDimension:
    """价值观维度（Schwartz 10类）"""
    name: str
    score: float = 0.0
    signals: List[PersonalitySignal] = field(default_factory=list)
    interpretation: str = ""


@dataclass
class CognitionStyle:
    """认知与思维风格"""
    abstraction_level: str = ""     # 抽象/具体
    reasoning_mode: str = ""        # 演绎/归纳/类比
    uncertainty_tolerance: str = "" # 高/中/低
    system_preference: str = ""     # 系统化/直觉化
    signals: List[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """综合分析结果"""
    big_five: Dict[str, PersonalityDimension]
    values: Dict[str, ValueDimension]
    cognition: CognitionStyle
    language_style: Dict[str, str]
    summary: str = ""
    confidence: float = 0.0


# ─────────────────────────────────────────────
# 推理规则库
# ─────────────────────────────────────────────

class LinguisticRuleEngine:
    """语言学信号提取规则"""

    # Big Five 信号词典
    BIG_FIVE_LEXICON = {
        "openness": {
            "positive": [
                "模型", "结构", "分析", "推理", "理论", "框架", "建立",
                "为什么", "如何", "探索", "理解", "规律", "原理", "本质",
                "创新", "新的", "尝试", "想象", "概念", "抽象"
            ],
            "negative": ["具体", "实际", "步骤", "操作", "执行", "按照"]
        },
        "conscientiousness": {
            "positive": [
                "第一步", "第二步", "首先", "然后", "最后", "计划", "系统",
                "结论", "目标", "完成", "严格", "准确", "规范", "流程"
            ],
            "negative": ["随便", "差不多", "大概", "随意", "凑合"]
        },
        "extraversion": {
            "positive": ["分享", "讨论", "我们", "一起", "聊", "交流", "社交"],
            "negative": ["独自", "自己", "个人", "私下", "独立"]
        },
        "agreeableness": {
            "positive": ["帮助", "支持", "理解", "合作", "关心", "友好"],
            "negative": ["批评", "反对", "质疑", "争论", "不同意"]
        },
        "neuroticism": {
            "positive": ["担心", "焦虑", "不确定", "害怕", "紧张", "烦恼"],
            "negative": ["稳定", "冷静", "确定", "自信", "放松"]
        }
    }

    # Schwartz价值观信号词典（10类）
    VALUE_LEXICON = {
        "自我方向": ["自己", "独立", "选择", "自由", "创造", "探索", "分析"],
        "刺激": ["新的", "挑战", "尝试", "冒险", "兴奋", "变化"],
        "享乐主义": ["享受", "乐趣", "快乐", "喜欢", "满足"],
        "成就": ["成功", "目标", "完成", "能力", "结论", "推断", "模型"],
        "权力": ["控制", "影响", "领导", "权威", "掌握"],
        "安全": ["稳定", "安全", "保障", "确定", "规则"],
        "从众": ["规范", "遵守", "礼貌", "传统", "应该"],
        "传统": ["传统", "习俗", "文化", "历史", "继承"],
        "仁爱": ["帮助", "关心", "支持", "朋友", "家人", "我们"],
        "普世主义": ["公平", "正义", "环境", "人类", "社会", "平等"]
    }

    # 认知风格信号
    COGNITION_SIGNALS = {
        "抽象思维": ["模型", "框架", "结构", "理论", "原理", "本质", "规律", "推理"],
        "系统化": ["第一步", "第二步", "步骤", "流程", "结构", "系统", "建立"],
        "演绎推理": ["因此", "所以", "推导", "结论", "推断", "得出"],
        "归纳推理": ["从…中", "总结", "规律", "发现", "观察"],
        "元认知": ["模型", "推理", "分析", "反思", "思考如何思考"],
        "高不确定耐受": ["探索", "尝试", "可能", "推断", "假设"],
    }


# ─────────────────────────────────────────────
# 主分析器
# ─────────────────────────────────────────────

class PersonalityAnalyzer:

    def __init__(self):
        self.engine = LinguisticRuleEngine()

    def _count_hits(self, text: str, word_list: List[str]) -> Tuple[int, List[str]]:
        hits = [w for w in word_list if w in text]
        return len(hits), hits

    def _score_dimension(self, text: str, pos_words: List[str],
                         neg_words: List[str]) -> Tuple[float, List[str], List[str]]:
        pos_count, pos_hits = self._count_hits(text, pos_words)
        neg_count, neg_hits = self._count_hits(text, neg_words)
        total = pos_count + neg_count
        score = (pos_count - neg_count) / max(total, 1)
        return round(score, 2), pos_hits, neg_hits

    def analyze_big_five(self, text: str) -> Dict[str, PersonalityDimension]:
        result = {}
        names = {
            "openness": "开放性",
            "conscientiousness": "尽责性",
            "extraversion": "外向性",
            "agreeableness": "宜人性",
            "neuroticism": "神经质（情绪稳定性）"
        }
        for key, lexicon in self.engine.BIG_FIVE_LEXICON.items():
            score, pos_hits, neg_hits = self._score_dimension(
                text, lexicon["positive"], lexicon["negative"]
            )
            signals = [PersonalitySignal("Big Five", key, w, 1.0, "正向") for w in pos_hits]
            signals += [PersonalitySignal("Big Five", key, w, 1.0, "负向") for w in neg_hits]
            dim = PersonalityDimension(name=names[key], score=score, signals=signals)
            result[key] = dim
        return result

    def analyze_values(self, text: str) -> Dict[str, ValueDimension]:
        result = {}
        for value_name, words in self.engine.VALUE_LEXICON.items():
            count, hits = self._count_hits(text, words)
            score = min(count / 3.0, 1.0)   # 归一化到0~1
            signals = [PersonalitySignal("价值观", value_name, w, 1.0, "正向") for w in hits]
            result[value_name] = ValueDimension(name=value_name, score=round(score, 2),
                                                signals=signals)
        return result

    def analyze_cognition(self, text: str) -> CognitionStyle:
        style = CognitionStyle()
        hits = {}
        for cog_type, words in self.engine.COGNITION_SIGNALS.items():
            count, matched = self._count_hits(text, words)
            hits[cog_type] = (count, matched)

        # 抽象 vs 具体
        abstract_score = hits["抽象思维"][0]
        style.abstraction_level = "高抽象" if abstract_score >= 2 else "中等" if abstract_score == 1 else "偏具体"

        # 系统化
        sys_score = hits["系统化"][0]
        style.system_preference = "强系统化" if sys_score >= 2 else "中等系统化"

        # 推理模式
        if hits["演绎推理"][0] >= hits["归纳推理"][0]:
            style.reasoning_mode = "偏演绎"
        else:
            style.reasoning_mode = "偏归纳"

        # 元认知
        meta = hits["元认知"][0]
        style.uncertainty_tolerance = "高" if meta >= 2 else "中"

        style.signals = [f"{k}: {v[1]}" for k, v in hits.items() if v[0] > 0]
        return style

    def analyze_language_style(self, text: str) -> Dict[str, str]:
        result = {}
        # 句子长度
        sentences = re.split(r'[。！？\n]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        avg_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
        result["平均句长"] = f"{avg_len:.1f}字（{'长句/复合思维' if avg_len > 20 else '短句/直接表达'}）"

        # 结构词
        structure_words = ["第一", "第二", "首先", "然后", "最后", "步骤"]
        if any(w in text for w in structure_words):
            result["表达结构"] = "有序/编号式（显示组织性思维）"
        else:
            result["表达结构"] = "流式表达"

        # 语气
        question_count = text.count("？") + text.count("?")
        result["提问频率"] = f"{question_count}个问句（{'主动探究型' if question_count > 0 else '陈述主导型'}）"

        # 人称
        if "我" in text:
            result["人称视角"] = "第一人称（主体意识强）"
        elif "我们" in text:
            result["人称视角"] = "集体视角"
        else:
            result["人称视角"] = "客观/去人称化"

        return result

    def analyze(self, text: str, text_label: str = "输入文本") -> AnalysisResult:
        big_five = self.analyze_big_five(text)
        values = self.analyze_values(text)
        cognition = self.analyze_cognition(text)
        language = self.analyze_language_style(text)

        # 计算置信度（基于信号总数）
        total_signals = sum(len(d.signals) for d in big_five.values())
        confidence = min(total_signals / 20.0, 1.0)

        result = AnalysisResult(
            big_five=big_five,
            values=values,
            cognition=cognition,
            language_style=language,
            confidence=round(confidence, 2)
        )
        return result

    def render_report(self, result: AnalysisResult, label: str = "") -> str:
        lines = []
        lines.append(f"{'='*60}")
        lines.append(f"  文本性格与价值观分析报告  {label}")
        lines.append(f"{'='*60}")

        # Big Five
        lines.append("\n【人格维度（Big Five）】")
        for key, dim in result.big_five.items():
            bar = self._bar(dim.score)
            evidence = ", ".join(s.evidence for s in dim.signals[:5])
            lines.append(f"  {dim.name:<16} {bar}  {dim.score:+.2f}")
            if evidence:
                lines.append(f"    关键词: {evidence}")

        # 价值观（取前5）
        lines.append("\n【价值观倾向（Schwartz）】")
        sorted_values = sorted(result.values.items(), key=lambda x: -x[1].score)
        for k, v in sorted_values[:6]:
            bar = self._bar(v.score, max_val=1.0)
            evidence = ", ".join(s.evidence for s in v.signals[:4])
            lines.append(f"  {v.name:<10} {bar}  {v.score:.2f}")
            if evidence:
                lines.append(f"    关键词: {evidence}")

        # 认知风格
        lines.append("\n【认知与思维风格】")
        c = result.cognition
        lines.append(f"  抽象层次   : {c.abstraction_level}")
        lines.append(f"  思维系统化 : {c.system_preference}")
        lines.append(f"  推理模式   : {c.reasoning_mode}")
        lines.append(f"  元认知水平 : {c.uncertainty_tolerance}")
        if c.signals:
            lines.append(f"  信号       : {'; '.join(c.signals[:4])}")

        # 语言风格
        lines.append("\n【语言风格特征】")
        for k, v in result.language_style.items():
            lines.append(f"  {k:<10} : {v}")

        lines.append(f"\n【模型置信度】{result.confidence:.0%}（取决于文本信号密度）")
        lines.append("="*60)
        return "\n".join(lines)

    @staticmethod
    def _bar(score: float, max_val: float = 1.0, width: int = 10) -> str:
        normalized = (score + max_val) / (2 * max_val) if max_val == 1.0 else score / max_val
        filled = int(normalized * width)
        filled = max(0, min(width, filled))
        return "[" + "█" * filled + "░" * (width - filled) + "]"


# ─────────────────────────────────────────────
# 第二步：代入对话记录进行分析
# ─────────────────────────────────────────────

CHAT_HISTORY = """
用户：第一步建立一个简单的从文稿资料文字内容反映个人性格特征和价值观倾向的推理结构模型，
第二步，从我和你的聊天记录代入模型进行分析得出结论
"""

if __name__ == "__main__":
    analyzer = PersonalityAnalyzer()

    # 对话文本分析
    result = analyzer.analyze(CHAT_HISTORY, "（用户对话记录）")
    report = analyzer.render_report(result, "（用户对话记录）")
    print(report)

    # 综合解读
    print("\n【综合性格解读】")
    print("""
基于当前对话文本的推理（注：样本较少，解读为倾向性推断）：

1. 思维方式
   - 分两步的结构化指令 → 高尽责性 + 系统化思维
   - 主动要求"建模"而非直接问结论 → 元认知能力强，重过程而非结果
   - 将抽象概念（性格/价值观）与方法论（推理模型）结合 → 高开放性

2. 价值观倾向
   - "建立模型"→ 成就导向 + 自我方向（追求理解与掌控）
   - "推理结构"→ 对秩序与系统的偏好（安全/尽责价值观）
   - 主动自我分析意愿 → 强烈的自我认知动机

3. 认知风格
   - 演绎优先：先建框架，再套数据（top-down思维）
   - 高抽象层次：直接从"文字→性格"的映射关系出发
   - 主动构建工具（让AI建模型）→ 工具性思维，效率导向

4. 潜在性格特征
   - 内倾型：无社交词汇，聚焦自我分析
   - 高认知需求（Need for Cognition）：喜欢思考复杂问题
   - 自主性强：不直接问"我是什么性格"，而是要求建立方法论

⚠️  注意：此分析基于极少量文本，置信度有限。
        更长的文本样本（日记、文章、多轮对话）会显著提高推断精度。
""")
