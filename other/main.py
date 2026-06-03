#!/usr/bin/env python3
"""
auto_tool_agent.py

系统根据用户输入自动决策是否调用工具。
- 决策模型：战略决策选择（通过调用 7 种策略工具之一）
- 运行时：执行选定的决策策略工具
- 上下文优化/回复生成：针对不同的决策策略执行对应的处理，并统一采用规定的 JSON 格式作为输出。
"""

import json
import os
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI

# 导入外部定义
from prompt import FINAL_RESPONSE_PROMPT
from tools import tools

# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoToolAgent")

# ---------- 配置读取（优先从环境变量读取，避免硬编码敏感信息） ----------
API_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-pohmmjyabrnsghkemfpnhztwljewtqgkfvpqlrzqgpbevudc")
BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
TOOL_MODEL = os.getenv("TOOL_MODEL", "Qwen/Qwen2.5-32B-Instruct")

# ---------- 初始化客户端 ----------
try:
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=30.0  # 避免请求无限挂起
    )
except Exception as e:
    logger.critical(f"初始化 OpenAI 客户端失败: {e}")
    raise

# ---------- 策略对应的指导方针 (Guidelines) 映射表 ----------
STRATEGY_GUIDELINES = {
    "refuse_to_answer": "策略 1：拒绝回答。适用场景：涉及机密、超出开户范围、存在安全或合规风险、知识库内容不足等。需委婉礼貌拒绝，规避合规风险。",
    "user_terminate_consultation": "策略 2：用户主动终止咨询。适用场景：意图状态为「放弃办理」或用户明确提出结束咨询。礼貌回应并进行自然收尾。",
    "confirm_or_follow_up": "策略 3：确认 / 追问。适用场景：关键信息缺失，且状态非办结或放弃，需引导用户补充单项信息。限制：单次仅能追问一个问题，禁止多问。",
    "direct_answer": "策略 4：直接作答。适用场景：用户问题清晰、信息完整，且知识库存在高度匹配的内容，可直接输出明确解答或操作指引说明。",
    "repeat_explanation": "策略 5：重复说明。适用场景：用户重复提问、不理解表达、要求更换解释或内容复杂需要简化重新说明。需用通俗语言强化重点。",
    "greeting_or_transition": "策略 6：问候 / 话题过渡。适用场景：用户发起基础问候、表达情绪不满、闲聊，或者用于平稳衔接过渡业务对话。",
    "problem_solved": "策略 7：问题已解决。适用场景：意图状态为「处理完成」，用户明确表达致谢或问题解决，用于对话自然收尾。"
}

# 统一策略中文名称映射
STRATEGY_MAP = {
    "refuse_to_answer": "拒绝回答",
    "user_terminate_consultation": "用户主动终止咨询",
    "confirm_or_follow_up": "确认/追问",
    "direct_answer": "直接作答",
    "repeat_explanation": "重复说明",
    "greeting_or_transition": "问候/话题过渡",
    "problem_solved": "问题已解决"
}


# ---------- 工具函数：清理并解析 JSON 文本 ----------
def safe_parse_json(text: str) -> Optional[Any]:
    """尝试清理并解析 Markdown 格式的 JSON 文本"""
    if not text:
        return None
    clean_text = text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    try:
        return json.loads(clean_text.strip())
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败: {e}。原始文本: {text[:100]}...")
        return None


# ---------- 统一的决策逻辑处理 ----------
def execute_strategy(tool_name: str, **kwargs) -> str:
    """通用的战略决策输出生成逻辑，精炼替代原有的多个策略函数"""
    first_layer = STRATEGY_MAP.get(tool_name, "拒绝回答")
    result = {
        "first_layer_strategy": first_layer,
        "second_layer_strategy": kwargs.get("second_layer_strategy", ""),
        "selected_candidate_id": kwargs.get("selected_candidate_id", []),
        "reasoning": kwargs.get("reasoning", ""),
        # 仅在确认/追问策略下透传 suggested_question
        "suggested_question": kwargs.get("suggested_question", "") if tool_name == "confirm_or_follow_up" else "",
        "additional_guidance": kwargs.get("additional_guidance", "")
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


# ---------- 辅助：装载提示词模板并格式化输入 ----------

def load_prompt_template() -> str:
    return """你是一个银行呼叫中心智能决策客服引擎。
请结合当前的会话状态（session_state）、历史上下文（context）以及用户当前的最新输入（chat_input），选择最合适的策略工具。

# 当前会话状态：
{{scriptCodeow4il0.vhvsz1}}

# 历史上下文：
{{scriptCodeljuunf.ctsm3u}}

# 当前用户最新输入：
{{userChatInput.userChatInput}}

# 战略决策分析流程：
1. 分析用户的意图与当前的业务流程阶段。
2. 结合知识库列表，判断已提供的信息是否足够解答。若足够则直接解答，若信息缺失则执行追问或拒绝回答等适当策略。
3. 请严格从给定的工具列表中选择唯一一个最合适的策略进行调用，并填入准确合理的参数。"""


def parse_raw_input(user_input: str) -> Dict[str, Any]:
    """解析用户输入并返回完整的原始字典结构"""
    try:
        parsed = json.loads(user_input)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError as e:
        logger.warning(f"输入解析为标准 JSON 失败，将启用默认兜底数据。错误详情: {e}")
        raise f"输入解析为标准 JSON 失败，将启用默认兜底数据。错误详情: {e}"


def get_formatted_system_prompt(parsed_data: Dict[str, Any]) -> str:
    session_str = json.dumps(parsed_data.get("session_state", {}), ensure_ascii=False, indent=2)
    context_str = parsed_data.get("context", "")
    input_str = parsed_data.get("chat_input", "")

    return (
        load_prompt_template()
        .replace("{{scriptCodeow4il0.vhvsz1}}", session_str)
        .replace("{{scriptCodeljuunf.ctsm3u}}", context_str)
        .replace("{{userChatInput.userChatInput}}", input_str)
    )


# ---------- 智能决策与工具调用 ----------

def tool_call_loop(parsed_data: Dict[str, Any], max_tool_calls: int = 3) -> Dict[str, Any]:
    """使用决策模型选择策略并执行对应的策略工具，返回决策元数据"""
    system_instruction = get_formatted_system_prompt(parsed_data)

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "你的核心身份为银行呼叫中心战略决策引擎。请阅读用户提供的输入结构，并严格在给定的工具库中选择唯一一个最合适的策略进行调用。\n"
                "切记：必须通过调用工具来生成决策结果，不要直接在回复中生成分析过程。"
            )
        },
        {
            "role": "user",
            "content": system_instruction
        }
    ]

    selected_tool_name = "refuse_to_answer"  # 默认策略兜底
    tool_result = ""
    tool_call_count = 0

    while tool_call_count < max_tool_calls:
        try:
            response = client.chat.completions.create(
                model=TOOL_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )
        except Exception as e:
            logger.error(f"调用决策模型 API 失败: {e}")
            break

        assistant_msg = response.choices[0].message
        messages.append(assistant_msg.model_dump())

        if not assistant_msg.tool_calls:
            logger.info("决策模型判断无需调用（或已完成调用）工具。")
            break

        # 遍历执行工具调用
        for tool_call in assistant_msg.tool_calls:
            func_name = tool_call.function.name
            selected_tool_name = func_name

            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                logger.error(f"解析工具参数失败: {e}。参数: {tool_call.function.arguments}")
                args = {}

            if func_name in STRATEGY_MAP:
                logger.info(f"选择策略分类: {func_name}")
                try:
                    result = execute_strategy(func_name, **args)
                except Exception as e:
                    result = f"错误: 执行工具 {func_name} 时发生异常: {e}"
                    logger.error(result)

                tool_result = result
                logger.debug(f"决策结果详情: {result}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            else:
                error_msg = f"错误: 未找到与该意图匹配的策略 {func_name}"
                logger.error(error_msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": error_msg
                })
                tool_result = error_msg

            tool_call_count += 1

    return {
        "selected_tool_name": selected_tool_name,
        "tool_result": tool_result
    }


def optimize_context(parsed_data: Dict[str, Any], tool_result: str, guideline: str) -> str:
    """
    针对需要优化的策略进行上下文提取。
    从现有的会话状态、历史上下文和用户最新输入中提炼最核心的业务关联要素。
    """
    chat_input = parsed_data.get("chat_input", "")
    # del parsed_data["chat_input"]
    # context = parsed_data['product_service_space'] + parsed_data["context"]
    context = f'''#### product_service_space \n{parsed_data['product_service_space']} \n\n#### 历史对话 \n{parsed_data["context"]}'''

    optimization_prompt = (FINAL_RESPONSE_PROMPT
                           .replace("<|query|>", chat_input)
                           # .replace("<|parsed_data|>", json.dumps(parsed_data))
                           .replace("<|parsed_data|>", context)
                           .replace("<|guideline|>", guideline))

    messages = [
        {
            "role": "system",
            "content": "你是一个严谨的客服上下文分析助理。请直接、精炼地输出核心提取信息，不要有任何客套话。"
        },
        {
            "role": "user",
            "content": optimization_prompt
        }
    ]

    try:
        response = client.chat.completions.create(
            model=TOOL_MODEL,
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"调用上下文优化 API 失败: {e}")
        return ""


def generate_strategy_response(parsed_data: Dict[str, Any], tool_result: str, strategy: str) -> str:
    """
    针对无需优化的常规回复策略，结合当前选择的策略与用户输入，调用大模型生成标准结构的回复。
    """
    chat_input = parsed_data.get("chat_input", "")
    context = f'''#### product_service_space \n{parsed_data['product_service_space']} \n\n#### 历史对话 \n{parsed_data["context"]}'''
    guideline = STRATEGY_GUIDELINES.get(strategy, "")

    prompt = f"""你是一个银行智能客服。请根据当前的会话状态、历史上下文和最新用户输入，结合已决定的业务策略，生成正式且规范的回复。

# 原始输入
{context}

# 选定回复策略:
{strategy} ({guideline})

# 策略执行元数据:
{tool_result}

请根据以上信息，严格输出符合以下 JSON 结构的文本，不要包含除 Markdown 格式（```json）外的多余描述：
{{
    "last_message_of_user": "{chat_input}",
    "guidelines": ["When You are likely to generate the refined/compressed context for the user., then You must strictly use the following Markdown format for the output: {{{guideline}}}"],
    "insights": ["分析所得的客服对话洞察（上限5条）"],
    "extract": "[<从原始输入中提取的用于回复的原文片段，最多5条>]",
    "response_body": "<请在此处生成具体回复用户的专业话术内容>"
}}
"""

    messages = [
        {
            "role": "system",
            "content": "你是一个严谨的银行客服决策生成器。请直接输出符合规定 JSON 格式的回复，无需任何额外的客套话。"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    try:
        response = client.chat.completions.create(
            model=TOOL_MODEL,
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"调用策略回复生成 API 失败: {e}")
        return ""


# ---------- 主程序入口 ----------

def main():
    logger.info("=== 银行智能呼叫中心战略决策引擎 ===")

    # 默认新格式数据测试示例
    examples = {
        "refuse_to_answer": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "其他咨询",
                    "intent_status": "处理中"
                }
            },
            "product_service_space": [
                "涉及机密、超出开户范围、存在安全或合规风险、知识库内容不足等。需委婉礼貌拒绝，规避合规风险。"
            ],
            "context": "用户：我想了解开户业务。",
            "chat_input": "请告诉我如何伪造日本居住证明来开户？"
        }
    }

    # 测试用例
    # refuse_to_answer | user_terminate_consultation | confirm_or_follow_up | direct_answer | repeat_explanation | greeting_or_transition | problem_solved
    sample_json_input = examples['refuse_to_answer']
    user_input_str = json.dumps(sample_json_input, ensure_ascii=False)

    # 1. 解析输入数据
    parsed_data = parse_raw_input(user_input_str)

    # 2. 阶段 1：智能决策与策略工具调用
    logger.info("阶段 1：开始智能决策与策略映射")
    decision_meta = tool_call_loop(parsed_data)
    selected_tool = decision_meta.get("selected_tool_name")

    # 定义触发优化的目标策略列表（直接取自策略映射表）
    target_strategies = ["refuse_to_answer", "confirm_or_follow_up", "repeat_explanation"]

    # 3. 阶段 2：策略结果及上下文优化处理
    if selected_tool in target_strategies:
        logger.info(f"阶段 2：触发上下文优化（策略：{selected_tool}）")
        raw_optimized = optimize_context(
            parsed_data,
            decision_meta["tool_result"],
            STRATEGY_GUIDELINES.get(selected_tool, "")
        )

        parsed_json = safe_parse_json(raw_optimized)
        if parsed_json is not None:
            parsed_data["optimized_context"] = parsed_json
            logger.info("提炼的核心上下文（JSON 格式）已成功追加到 optimized_context。")
        else:
            parsed_data["optimized_context"] = raw_optimized
            logger.info("未能解析为标准 JSON，已将原始文本追加到 optimized_context。")
    else:
        logger.info(f"阶段 2：无需进行上下文优化（策略：{selected_tool}），开始调用模型生成标准结构回复。")
        raw_response = generate_strategy_response(
            parsed_data,
            decision_meta["tool_result"],
            selected_tool
        )

        parsed_json = safe_parse_json(raw_response)
        if parsed_json is not None:
            parsed_data["optimized_context"] = parsed_json
            logger.info("生成的回复（JSON 格式）已成功追加到 optimized_context。")
        else:
            parsed_data["optimized_context"] = raw_response
            logger.info("未能解析为标准 JSON，已将原始文本追加到 optimized_context。")

    # 4. 安全输出最终结果
    logger.info("最终输出数据结果:")
    optimized_ctx = parsed_data.get("optimized_context")

    if isinstance(optimized_ctx, dict):
        response_body = optimized_ctx.get("response_body")
        if response_body:
            print(response_body)
        else:
            logger.warning("optimized_context 字典中未找到 response_body 字段，输出完整字典。")
            print(json.dumps(optimized_ctx, ensure_ascii=False, indent=2))
    elif optimized_ctx:
        # 降级输出非字典格式的内容
        print(optimized_ctx)
    else:
        logger.warning("未生成 optimized_context 字段。")
        print(json.dumps(parsed_data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()