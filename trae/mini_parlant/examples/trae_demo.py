"""
mini_parlant + SiliconFlow API 完整流程整合演示

本demo将所有功能整合为一个完整的交互式系统，用户输入查询后：
1. 自动解析输入（查询、历史、知识、元数据）
2. 检测信号类型
3. 选择合适策略
4. 检查知识充分性
5. 执行补全循环（如需要）
6. 生成最终回答

运行方式：
    python examples/trae_demo.py

需要从 https://cloud.siliconflow.cn/ 获取API密钥
"""

import sys
import os

# 添加项目路径到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openai
from typing import Optional, Sequence, Dict, List

from mini_parlant import MiniParlantRuntime, RuntimeConfig, DecisionMode
from mini_parlant.models import (
    ContextBundle, Signal, SignalType, StructuredResponse, 
    StrategyResult, SufficiencyVerdict
)
from mini_parlant.enricher import Enricher
from mini_parlant.registry import BaseStrategy
from mini_parlant.sufficiency import SufficiencyChecker


# ---------------------------------------------------------------------------
# 1. 配置SiliconFlow API连接
# ---------------------------------------------------------------------------

BASE_URL = "https://api-inference.modelscope.cn/v1"
MODEL = "deepseek-ai/DeepSeek-V4-Flash"
API_KEY = "ms-5e8ac3d3-3104-47b9-bf52-e96706571e23"  # 请替换为您的实际API密钥


def create_siliconflow_caller(base_url: str, api_key: str, model: str) -> callable:
    """创建SiliconFlow API调用器"""
    client = openai.OpenAI(base_url=base_url, api_key=api_key)
    
    def llm_caller(prompt: str) -> str:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1024,
                timeout=30,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[LLM调用错误: {str(e)}]"
    
    return llm_caller


# ---------------------------------------------------------------------------
# 2. 定义工具函数（用于知识补全）
# ---------------------------------------------------------------------------

def weather_tool(city: str) -> str:
    """模拟天气查询工具"""
    weather_data = {
        "beijing": "北京：晴天，28°C，湿度45%",
        "shanghai": "上海：多云，25°C，湿度70%",
        "paris": "巴黎：雨天，18°C，湿度85%",
        "new york": "纽约：晴转多云，22°C，湿度60%",
        "london": "伦敦：阴天，15°C，湿度75%",
    }
    city_lower = city.lower().strip()
    return weather_data.get(city_lower, f"未找到 {city} 的天气数据")


def time_tool(city: str) -> str:
    """模拟时区查询工具"""
    time_data = {
        "beijing": "北京当前时间：UTC+8",
        "shanghai": "上海当前时间：UTC+8",
        "paris": "巴黎当前时间：UTC+1",
        "new york": "纽约当前时间：UTC-4",
        "tokyo": "东京当前时间：UTC+9",
    }
    city_lower = city.lower().strip()
    return time_data.get(city_lower, f"未找到 {city} 的时区信息")


# ---------------------------------------------------------------------------
# 3. 自定义策略（情感分析）
# ---------------------------------------------------------------------------

class SentimentAnalysisStrategy(BaseStrategy):
    """情感分析策略 - 处理情感相关查询"""
    priority = 5  # 高于默认策略
    
    def matches(self, context: ContextBundle, signals: Sequence[Signal]) -> bool:
        sentiment_keywords = {"感觉", "心情", "情绪", "开心", "难过", "生气", "伤心", "郁闷", "沮丧"}
        return any(kw in context.query for kw in sentiment_keywords)
    
    def execute(self, context: ContextBundle, signals: Sequence[Signal]) -> StrategyResult:
        return StrategyResult(
            goal=f'分析用户的情感状态："{context.query}"',
            constraints=["保持同理心", "回应要简洁", "用中文回复"],
            output_format="首先描述检测到的情感，然后提供一个支持性的回应。",
            strategy_name=self.name,
        )


# ---------------------------------------------------------------------------
# 4. 创建完整的运行时实例
# ---------------------------------------------------------------------------

def create_integrated_runtime(llm_caller: callable) -> MiniParlantRuntime:
    """创建整合了所有功能的运行时实例"""
    
    # 创建Enricher，注册工具
    enricher = Enricher(tools={
        "weather": weather_tool,
        "time": time_tool,
    })
    
    # 创建运行时配置
    config = RuntimeConfig(
        decision_mode=DecisionMode.LOGIC,  # 使用逻辑决策模式
        max_enrichment_loops=1,            # 允许一次补全循环
        llm_caller=llm_caller,
    )
    
    # 创建运行时
    runtime = MiniParlantRuntime(
        config=config,
        enricher=enricher,
    )
    
    # 注册自定义策略
    runtime.registry.register(SentimentAnalysisStrategy())
    
    return runtime


# ---------------------------------------------------------------------------
# 5. 完整流程演示函数
# ---------------------------------------------------------------------------

def run_complete_pipeline(runtime: MiniParlantRuntime, user_input: str, show_details: bool = True) -> StructuredResponse:
    """
    执行完整的数据处理流程：
    1. 解析输入 → 2. 检测信号 → 3. 选择上下文 → 4. 充分性检查 → 
    5. 补全循环 → 6. 策略选择 → 7. 执行策略 → 8. 生成回答
    """
    print("\n" + "-" * 70)
    print("开始完整流程处理...")
    print("-" * 70)
    
    # 步骤1: 解析输入
    if show_details:
        print("\n[步骤1/8] 解析输入文本")
        print("正在提取查询、对话历史、知识库和元数据...")
    
    # 步骤2: 检测信号
    if show_details:
        print("\n[步骤2/8] 检测信号类型")
        print("分析查询意图和特征...")
    
    # 步骤3: 选择上下文
    if show_details:
        print("\n[步骤3/8] 选择上下文")
        print("筛选与查询相关的知识和历史...")
    
    # 步骤4: 充分性检查
    if show_details:
        print("\n[步骤4/8] 充分性检查")
        print("评估当前知识是否足够回答查询...")
    
    # 步骤5: 补全循环（如需要）
    if show_details:
        print("\n[步骤5/8] 知识补全循环")
        print("检查是否需要调用工具补充知识...")
    
    # 步骤6: 策略选择
    if show_details:
        print("\n[步骤6/8] 策略选择")
        print("根据信号选择最佳策略...")
    
    # 步骤7: 执行策略
    if show_details:
        print("\n[步骤7/8] 执行策略")
        print("生成Prompt配方...")
    
    # 步骤8: 生成回答
    if show_details:
        print("\n[步骤8/8] 生成回答")
        print("调用LLM生成最终响应...")
    
    # 执行完整流程
    response = runtime.run(user_input)
    
    return response


def display_response(response: StructuredResponse):
    """展示处理结果详情"""
    print("\n" + "=" * 70)
    print("处理结果详情")
    print("=" * 70)
    
    print(f"\n【使用策略】: {response.strategy_used}")
    print(f"【检测到的信号】: {[s.type.value for s in response.signals]}")
    print(f"【信号详情】:")
    for signal in response.signals:
        print(f"  - {signal.type.value} (置信度: {signal.confidence:.2f})")
    
    print(f"\n【是否经过补全】: {'是' if response.enriched else '否'}")
    if response.enriched:
        print(f"【补全备注】: {response.enrichment_notes}")
    
    print(f"\n【元数据】:")
    if response.metadata:
        for key, value in response.metadata.items():
            print(f"  - {key}: {value}")
    
    print("\n【最终回答】:")
    print("-" * 40)
    print(response.answer)
    print("-" * 40)


# ---------------------------------------------------------------------------
# 6. 交互式主界面
# ---------------------------------------------------------------------------

def interactive_mode(runtime: MiniParlantRuntime):
    """交互式演示模式"""
    print("\n" + "=" * 70)
    print("mini_parlant 交互式演示")
    print("=" * 70)
    print("\n欢迎使用mini_parlant框架！")
    print("您可以输入查询，系统会自动处理并返回结果。")
    print("\n输入格式示例：")
    print("""
Query:
您的问题或请求

History:
User: 之前的对话历史（可选）
Assistant: 之前的回答（可选）

Knowledge:
相关知识（可选）

Metadata:
key=value（可选）
""")
    print("输入 'exit' 或 'quit' 退出。")
    print("-" * 70)
    
    while True:
        print("\n请输入您的查询：")
        print("-" * 40)
        
        # 读取多行输入
        lines = []
        while True:
            try:
                line = input()
                if line.strip().lower() in ('exit', 'quit'):
                    print("\n感谢使用！再见！")
                    return
                if line.strip() == '':
                    break
                lines.append(line)
            except EOFError:
                break
        
        user_input = "\n".join(lines)
        
        if not user_input.strip():
            print("请输入有效的查询内容！")
            continue
        
        # 执行完整流程
        response = run_complete_pipeline(runtime, user_input)
        
        # 展示结果
        display_response(response)


# ---------------------------------------------------------------------------
# 7. 预设示例演示
# ---------------------------------------------------------------------------

def preset_demo(runtime: MiniParlantRuntime):
    """运行预设示例演示完整流程"""
    print("\n" + "=" * 70)
    print("预设示例演示")
    print("=" * 70)
    
    # 示例1: 简单问答（带知识库）
    print("\n【示例1】基于知识库的问答")
    print("-" * 50)
    input1 = """
Query:
法国的首都是什么？

Knowledge:
法国是西欧的一个国家。
巴黎是法国的首都和最大城市，位于法国北部。
埃菲尔铁塔位于巴黎。

Metadata:
locale=zh-CN
"""
    response1 = run_complete_pipeline(runtime, input1, show_details=False)
    display_response(response1)
    
    # 示例2: 需要补全的查询
    print("\n【示例2】需要知识补全的查询")
    print("-" * 50)
    input2 = """
Query:
今天巴黎的天气怎么样？
"""
    response2 = run_complete_pipeline(runtime, input2, show_details=False)
    display_response(response2)
    
    # 示例3: 情感分析
    print("\n【示例3】情感分析查询")
    print("-" * 50)
    input3 = """
Query:
我今天感觉非常难过，工作上遇到了很多困难。
"""
    response3 = run_complete_pipeline(runtime, input3, show_details=False)
    display_response(response3)
    
    # 示例4: 任务规划
    print("\n【示例4】任务规划查询")
    print("-" * 50)
    input4 = """
Query:
帮我创建一个学习Python的一周计划。

Knowledge:
Python是一种流行的编程语言。
Python可以用于Web开发、数据分析、人工智能等领域。
"""
    response4 = run_complete_pipeline(runtime, input4, show_details=False)
    display_response(response4)


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("mini_parlant + SiliconFlow 完整流程整合演示")
    print("=" * 70)
    print("\n框架功能概览：")
    print("1. 输入解析 → 提取查询、历史、知识、元数据")
    print("2. 信号检测 → 识别查询类型（问题、任务、情感等）")
    print("3. 策略选择 → 根据信号选择最佳处理策略")
    print("4. 充分性检查 → 判断知识是否足够回答")
    print("5. 知识补全 → 调用工具补充缺失信息")
    print("6. Prompt组合 → 生成结构化提示")
    print("7. LLM调用 → 生成最终回答")
    print("\n当前配置：")
    print(f"  - 模型: {MODEL}")
    print(f"  - API端点: {BASE_URL}")
    print(f"  - 决策模式: Logic")
    print(f"  - 最大补全循环: 1")
    print("=" * 70)
    
    # 创建LLM调用器
    llm_caller = create_siliconflow_caller(BASE_URL, API_KEY, MODEL)
    
    # 创建整合的运行时实例
    runtime = create_integrated_runtime(llm_caller)
    
    # 选择运行模式
    print("\n请选择运行模式：")
    print("1. 预设示例演示（自动运行4个示例）")
    print("2. 交互式模式（手动输入查询）")
    
    while True:
        choice = input("\n请输入选择 (1/2): ").strip()
        if choice == '1':
            preset_demo(runtime)
            break
        elif choice == '2':
            interactive_mode(runtime)
            break
        else:
            print("无效选择，请输入1或2")
    
    print("\n" + "=" * 70)
    print("演示完成！")
    print("=" * 70)