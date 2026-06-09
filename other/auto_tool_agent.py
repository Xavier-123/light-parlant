#!/usr/bin/env python3
"""
auto_tool_agent.py

系统根据用户输入自动决策是否调用工具。
- 阶段 0：Skill 预处理（业务逻辑判定，命中则直接截断返回）
- 阶段 1：决策模型战略决策选择（通过调用 7 种策略工具之一）
- 阶段 2：运行时执行选定的决策策略工具
- 阶段 3：上下文优化/回复生成
- API 接口：提供 /dynamic_context_manager 接口进行交互
"""

import json
import os
import logging
import re
from typing import List, Dict, Any, Optional
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

# 导入外部定义
from prompt import FINAL_RESPONSE_PROMPT
from skill import TokyoStarCounterOpenSkill, TokyoStarOnlineAddressModSkill, BaseSkill
from tools import tools

# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoToolAgent")

# ---------- 配置读取（优先从环境变量读取，避免硬编码敏感信息） ----------
API_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-duhwosgxlixiqnoeremlimqgorstljququocpbyrkyfxwuih")
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

# ==================== Skill 预处理层设计与定义 ====================
# 注册 Skill 列表 (极易扩展，只需定义新的 Skill 类并追加至此处)
SKILLS_REGISTRY: List[BaseSkill] = [
    TokyoStarCounterOpenSkill(client, model=TOOL_MODEL),
    TokyoStarOnlineAddressModSkill(client, model=TOOL_MODEL)
]


def evaluate_skills(parsed_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Skill 预处理评估模块。
    遍历注册的 Skill，检测到匹配时直接触发其判定逻辑。
    """
    for skill in SKILLS_REGISTRY:
        if skill.match(parsed_data):
            logger.info(f"成功匹配业务 Skill 触发条件: {skill.chinese_name}")
            prompt = skill.execute(parsed_data)
            return {
                "selected_strategy": skill.name,
                "selected_strategy_chinese_name": skill.chinese_name,
                "prompt": prompt
            }
    return None


# =================================================================


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
                tool_call_count += 1
                break
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
    context = f'''#### product_service_space \n{parsed_data.get('product_service_space', [])} \n\n#### 历史对话 \n{parsed_data.get("context", "")}'''

    optimization_prompt = (FINAL_RESPONSE_PROMPT
                           .replace("<|query|>", chat_input)
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
    logger.debug(f"optimization_prompt: \n{optimization_prompt}")
    return optimization_prompt


# ---------- FastAPI 接口定义 ----------

app = FastAPI(title="Bank Smart Call Center Decision Engine API", version="1.0.0")


# 定义请求数据模型
class SessionState(BaseModel):
    intent_space: Optional[Dict[str, Any]] = Field(default=None)


class DecisionRequest(BaseModel):
    session_id: str
    agent_id: str
    session_state: Optional[SessionState] = Field(default=None)
    product_service_space: Optional[List[str]] = Field(default_factory=list)
    context: Optional[str] = Field(default="")
    chat_input: str


@app.post("/dynamic_context_manager")
async def dynamic_context_manager(request: DecisionRequest):
    """
    智能呼叫中心战略决策引擎 API 接口。
    接收当前会话状态、历史上下文和用户输入，返回决策分类与优化后的上下文或具体回复内容。
    """
    try:
        # 将传入的 Pydantic 模型转换为字典以便后续逻辑处理
        parsed_data = request.model_dump()

        # 1. 阶段 0：Skill 预处理模块检测
        logger.info("阶段 0：启动 Skill 预处理评估")
        skill_response = evaluate_skills(parsed_data)

        if skill_response is not None:
            logger.info(f"Skill 预处理拦截成功，执行业务 Skill 并截断后续策略流程。")
            return {
                "session_id": request.session_id,
                "agent_id": request.agent_id,
                "selected_strategy": skill_response["selected_strategy"],
                "selected_strategy_chinese_name": skill_response["selected_strategy_chinese_name"],
                "tool_result": None,
                "prompt": skill_response["prompt"],
            }

        # 2. 阶段 1：无 Skill 命中，走原有智能决策逻辑与策略映射
        logger.info("阶段 1：未触发业务 Skill，启动智能决策与策略映射")
        decision_meta = tool_call_loop(parsed_data)
        selected_tool = decision_meta.get("selected_tool_name")

        # 定义触发优化的目标策略列表
        target_strategies = list(STRATEGY_GUIDELINES.keys())

        # 3. 阶段 2：策略结果及上下文优化处理
        raw_response = ""
        if selected_tool in target_strategies:
            logger.info(f"阶段 2：触发上下文优化（策略：{selected_tool}）")
            raw_response = optimize_context(
                parsed_data,
                decision_meta["tool_result"],
                STRATEGY_GUIDELINES.get(selected_tool, "")
            )

        return {
            "session_id": request.session_id,
            "agent_id": request.agent_id,
            "selected_strategy": selected_tool,
            "selected_strategy_chinese_name": STRATEGY_MAP.get(selected_tool, "未知策略"),
            "tool_result": decision_meta.get("tool_result"),
            "prompt": raw_response,
        }

    except Exception as e:
        logger.error(f"处理决策引擎请求失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"内部决策处理异常: {str(e)}")


if __name__ == "__main__":
    # 本地直接启动服务（默认端口：8000）
    uvicorn.run(app, host="0.0.0.0", port=8000)
