#!/usr/bin/env python3
"""
auto_tool_agent.py

系统根据用户输入自动决策是否调用工具。
- 决策模型：战略决策选择（通过调用 7 种策略工具之一）
- 运行时：执行选定的决策策略工具
- 上下文优化：若决策为拒绝回答(1)、确认/追问(3)或重复说明(5)，则提取核心业务信息并追加至 `optimized_context` 字段返回；否则原样输出输入结构。
"""

import json
from typing import List, Dict, Any
from openai import OpenAI
from prompt import FINAL_RESPONSE_PROMPT

# ---------- 导入外部工具定义 ----------
from tools import tools

# ---------- 初始化 ----------
client = OpenAI(
    base_url="https://api.siliconflow.cn/v1",
    api_key="sk-pohmmjyabrnsghkemfpnhztwljewtqgkfvpqlrzqgpbevudc",
)
TOOL_MODEL = "Qwen/Qwen2.5-32B-Instruct"  # 快速决策模型

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


# ---------- 7 种策略工具的 Python 逻辑实现 ----------

def handle_strategy(first_layer_strategy: str, **kwargs) -> str:
    """通用的战略决策输出生成逻辑"""
    result = {
        "first_layer_strategy": first_layer_strategy,
        "second_layer_strategy": kwargs.get("second_layer_strategy", ""),
        "selected_candidate_id": kwargs.get("selected_candidate_id", []),
        "reasoning": kwargs.get("reasoning", ""),
        "suggested_question": kwargs.get("suggested_question", ""),
        "additional_guidance": kwargs.get("additional_guidance", "")
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


def refuse_to_answer(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                     additional_guidance: str = "") -> str:
    """策略 1：拒绝回答。"""
    return handle_strategy(
        "拒绝回答",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


def user_terminate_consultation(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                                additional_guidance: str = "") -> str:
    """策略 2：用户主动终止咨询。"""
    return handle_strategy(
        "用户主动终止咨询",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


def confirm_or_follow_up(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                         suggested_question: str, additional_guidance: str = "") -> str:
    """策略 3：确认 / 追问。"""
    return handle_strategy(
        "确认/追问",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question=suggested_question,
        additional_guidance=additional_guidance
    )


def direct_answer(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                  additional_guidance: str = "") -> str:
    """策略 4：直接作答。"""
    return handle_strategy(
        "直接作答",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


def repeat_explanation(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                       additional_guidance: str = "") -> str:
    """策略 5：重复说明。"""
    return handle_strategy(
        "重复说明",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


def greeting_or_transition(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                           additional_guidance: str = "") -> str:
    """策略 6：问候 / 话题过渡。"""
    return handle_strategy(
        "问候/话题过渡",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


def problem_solved(second_layer_strategy: str, selected_candidate_id: List[str], reasoning: str,
                   additional_guidance: str = "") -> str:
    """策略 7：问题已解决。"""
    return handle_strategy(
        "问题已解决",
        second_layer_strategy=second_layer_strategy,
        selected_candidate_id=selected_candidate_id,
        reasoning=reasoning,
        suggested_question="",
        additional_guidance=additional_guidance
    )


# 策略函数映射表
tool_mapping = {
    "refuse_to_answer": refuse_to_answer,
    "user_terminate_consultation": user_terminate_consultation,
    "confirm_or_follow_up": confirm_or_follow_up,
    "direct_answer": direct_answer,
    "repeat_explanation": repeat_explanation,
    "greeting_or_transition": greeting_or_transition,
    "problem_solved": problem_solved
}


# ---------- 辅助：装载提示词模板并格式化输入 ----------

def load_prompt_template() -> str:
    """定义底层决策引擎的系统提示词模板"""
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
    """
    解析用户输入并返回完整的原始字典结构，解析失败则提供默认兜底数据。
    """
    try:
        parsed = json.loads(user_input)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        print(f"[提示] 输入解析为标准 JSON 失败，将启用默认兜底数据。错误详情: {e}")

    # 兜底默认数据
    return {
        "session_state": {
            "intent_space": {
                "primary_intent": "开户业务",
                "secondary_intent": "开户资质",
                "intent_status": "处理中"
            },
            "product_service_space": [
                {
                    "knowledge_id": "k1",
                    "summary": "基本开户资质",
                    "content": "年满18岁且居住于日本境内的个人可申请开户。"
                }
            ],
            "user_space": {
                "是否年满18岁": "",
                "国籍": "日本"
            }
        },
        "context": "客服：您好，请问有什么可以帮您？\n用户：我想在日本开户，我是日本国籍。",
        "chat_input": "我想在日本开户，我是日本国籍。"
    }


def get_formatted_system_prompt(parsed_data: Dict[str, Any]) -> str:
    """将结构化数据渲染进提示词模板中"""
    template = load_prompt_template()

    session_str = json.dumps(parsed_data.get("session_state", {}), ensure_ascii=False, indent=2)
    context_str = parsed_data.get("context", "")
    input_str = parsed_data.get("chat_input", "")

    formatted = template
    formatted = formatted.replace("{{scriptCodeow4il0.vhvsz1}}", session_str)
    formatted = formatted.replace("{{scriptCodeljuunf.ctsm3u}}", context_str)
    formatted = formatted.replace("{{userChatInput.userChatInput}}", input_str)

    return formatted


# ---------- 智能决策与工具调用 ----------

def tool_call_loop(parsed_data: Dict[str, Any], max_tool_calls: int = 3) -> Dict[str, Any]:
    """
    使用决策模型选择策略并执行对应的策略工具，返回决策元数据
    """
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

    selected_tool_name = "direct_answer"  # 默认策略兜底
    tool_result = ""

    tool_call_count = 0
    while tool_call_count < max_tool_calls:
        response = client.chat.completions.create(
            model=TOOL_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg.model_dump())

        if not assistant_msg.tool_calls:
            print("[决策] 决策模型判断无需调用工具。")
            break

        for tool_call in assistant_msg.tool_calls:
            func_name = tool_call.function.name
            selected_tool_name = func_name

            try:
                args = json.loads(tool_call.function.arguments)
            except Exception:
                args = {}

            if func_name in tool_mapping:
                print(f"[战略决策调用] 选择策略分类: {func_name}")
                result = tool_mapping[func_name](**args)
                tool_result = result
                print(f"[决策结果详情] {result[:120]}...")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
                tool_call_count += 1
            else:
                error_msg = f"错误: 未找到与该意图匹配的策略 {func_name}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": error_msg
                })
                tool_result = error_msg
                tool_call_count += 1

        break

    return {
        "selected_tool_name": selected_tool_name,
        "tool_result": tool_result
    }


def optimize_context(parsed_data: Dict[str, Any], tool_result: str, guideline: Any) -> str:
    """
    针对 拒绝回答、确认/追问 与 重复说明 策略进行上下文优化。
    从现有的会话状态、历史上下文和用户最新输入中提炼最核心的业务关联要素。
    """
    session_state = json.dumps(parsed_data.get("session_state", {}), ensure_ascii=False, indent=2)
    # session_state = json.dumps(parsed_data.get("session_state", {}).get("product_service_space", {}), ensure_ascii=False, indent=2)
    context = parsed_data.get("context", "")
    chat_input = parsed_data.get("chat_input", "")
    optimization_prompt = (FINAL_RESPONSE_PROMPT
                           .replace("<|query|>", chat_input)
                           .replace("<|history|>", context)
                           .replace("<|session_state|>", session_state)
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

    response = client.chat.completions.create(
        model=TOOL_MODEL,
        messages=messages
    )
    response_content = response.choices[0].message.content.strip()
    return response_content


def main():
    print("=== 银行智能呼叫中心战略决策引擎 ===")

    # 默认新格式数据测试示例
    exapmles = {
        "refuse_to_answer": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "其他咨询",
                    "intent_status": "处理中"
                }
            },
            "context": "用户：我想了解开户业务。",
            "chat_input": "请告诉我如何伪造日本居住证明来开户？"
        },
        "user_terminate_consultation": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "开户申请",
                    "intent_status": "放弃办理"
                }
            },
            "context": "客服：请提供您的居住地址。",
            "chat_input": "算了，我不办了，谢谢。"
        },
        "confirm_or_follow_up": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "开户资质",
                    "intent_status": "处理中"
                },
                "product_service_space": [
                    {
                        "knowledge_id": "k1",
                        "summary": "基本开户资质",
                        "content": "年满18岁且居住于日本境内的个人可申请开户。"
                    }
                ],
                "user_space": {
                    "是否年满18岁": "",
                    "国籍": "日本"
                }
            },
            "context": "客服：您好，请问有什么可以帮您？\n用户：我想在日本开户，我是日本国籍。",
            "chat_input": "我想在日本开户，我是日本国籍。"
        },
        "direct_answer": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "开户资质",
                    "intent_status": "处理中"
                },
                "product_service_space": [
                    {
                        "knowledge_id": "k1",
                        "summary": "开户年龄要求",
                        "content": "年满18岁且居住于日本境内可申请开户。"
                    }
                ]
            },
            "context": "",
            "chat_input": "开户年龄要求是多少？"
        },
        "repeat_explanation": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "开户资质",
                    "intent_status": "处理中"
                }
            },
            "context": "客服：开户要求年满18岁且居住于日本。\n用户：没太明白。\n客服：就是需要满足年龄和居住条件。",
            "chat_input": "还是没懂，你能再简单解释一下吗？"
        },
        "greeting_or_transition": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "",
                    "secondary_intent": "",
                    "intent_status": "处理中"
                }
            },
            "context": "",
            "chat_input": "你好，请问有人吗？"
        },
        "problem_solved": {
            "session_state": {
                "intent_space": {
                    "primary_intent": "开户业务",
                    "secondary_intent": "开户申请",
                    "intent_status": "处理完成"
                }
            },
            "context": "客服：您的开户申请已经成功提交。",
            "chat_input": "好的，问题已经解决了，谢谢你。"
        }
    }

    # refuse_to_answer | user_terminate_consultation | confirm_or_follow_up | direct_answer | repeat_explanation | greeting_or_transition | problem_solved
    sample_json_input = exapmles['problem_solved']
    user_input_str = json.dumps(sample_json_input, ensure_ascii=False)

    # 解析输入负载，保留原样结构
    parsed_data = parse_raw_input(user_input_str)

    # 阶段 1：智能决策与策略工具调用
    print("\n⚙️ 阶段 1：智能决策与策略映射")
    decision_meta = tool_call_loop(parsed_data)
    selected_tool = decision_meta.get("selected_tool_name")

    # 阶段 2：根据策略结果进行逻辑分支处理
    # target_strategies = ["refuse_to_answer", "confirm_or_follow_up", "repeat_explanation"]
    target_strategies = ["refuse_to_answer", "user_terminate_consultation", "confirm_or_follow_up", "direct_answer", "repeat_explanation", "greeting_or_transition", "problem_solved"]

    if selected_tool in target_strategies:
        print(f"\n⚙️ 阶段 2：触发上下文优化（策略：{selected_tool}）")
        raw_optimized = optimize_context(parsed_data, decision_meta["tool_result"], STRATEGY_GUIDELINES[selected_tool])

        # 尝试将优化结果解析为 JSON 以保持最终输出的结构规范，解析失败则保留纯文本
        try:
            # 清除可能带有的 markdown 代码包裹
            clean_ctx = raw_optimized.strip()
            if clean_ctx.startswith("```json"):
                clean_ctx = clean_ctx[7:]
            elif clean_ctx.startswith("```"):
                clean_ctx = clean_ctx[3:]
            if clean_ctx.endswith("```"):
                clean_ctx = clean_ctx[:-3]

            parsed_data["optimized_context"] = json.loads(clean_ctx.strip())
        except Exception:
            parsed_data["optimized_context"] = raw_optimized

        print("[提炼核心上下文已追加]")
    else:
        print(f"\n⚙️ 阶段 2：无需进行上下文优化（策略：{selected_tool}），保持原结构返回。")

    # 输出最终返回给程序的结构
    print("\n🤖 最终输出数据结果:")
    # print(json.dumps(parsed_data, ensure_ascii=False, indent=2))
    print(parsed_data['optimized_context']['response_body'])


if __name__ == "__main__":
    main()
