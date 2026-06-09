import logging
from typing import Dict, Any
from prompt import TOKYO_STAR_ONLINE_ADDRESS_MOD_SKILL_PROMPT, TOKYO_STAR_COUNTER_OPEN_SKILL_PROMPT

logger = logging.getLogger("AutoToolAgent")

# ==================== Skill 预处理层设计与定义 ====================

class BaseSkill:
    """所有业务 Skill 的基类"""
    name: str = ""
    chinese_name: str = ""

    def __init__(self, llm_client, model="gpt-4o-mini"):
        """
        初始化时支持传入大模型调用函数。
        """
        self.llm_client = llm_client
        self.model = model

    def call_llm(self, prompt: str) -> str:
        """调用大模型的辅助方法"""
        try:
            response = self.llm_client.chat.completions.create(
                model=self.model,  # 可根据实际部署的模型进行调整
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # 设为 0 以获得最稳定的判定结果
                max_tokens=30  # 意图匹配仅需输出 YES/NO，限制 Token 数量以降低延迟
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            # 实际生产环境中建议使用 log 模块记录异常
            logger.error(f"OpenAI API 调用异常: {e}")
            raise e

    def match(self, parsed_data: Dict[str, Any]) -> bool:
        """
        判断当前用户请求是否匹配该 Skill 的触发场景。
        """
        raise NotImplementedError("Skills must implement the 'match' method.")

    def execute(self, parsed_data: Dict[str, Any]) -> str:
        """
        匹配成功后的核心业务判定逻辑，返回处理方案。
        """
        raise NotImplementedError("Skills must implement the 'execute' method.")


class TokyoStarCounterOpenSkill(BaseSkill):
    """
    Skill 1: 东京之星银行个人柜台开户资格审核
    """
    name = "tokyo_star_counter_open_audit"
    chinese_name = "东京之星银行个人柜台开户资格审核"

    def match(self, parsed_data: Dict[str, Any]) -> bool:
        chat_input = parsed_data.get("chat_input", "")
        context = parsed_data.get("context", "")
        full_text = f"用户输入: {chat_input}\n上下文历史: {context}"

        prompt = (
            "你是一个业务意图识别助手。请分析以下用户的输入和上下文，判断用户的意图是否符合“东京之星银行个人柜台开户资格审核”场景。\n\n"
            "【匹配条件】\n"
            "- 核心意图：客户希望办理或咨询“个人柜台开户”、“线下柜面开户”相关的资格审核或流程。\n\n"
            "【排除条件】\n"
            "- 涉及“法人”、“企业”开户。\n"
            "- 明确指向非柜台渠道（如：网上开户、在线开户、网银开户、APP开户等）。\n\n"
            f"【对话内容】\n{full_text}\n\n"
            "【输出要求】\n"
            "如果用户意图符合匹配条件，且不满足排除条件，请直接输出 \"YES\"；否则输出 \"NO\"。请勿包含任何其他多余的解释、标点或回复。"
        )

        try:
            response = self.call_llm(prompt)
            cleaned_response = response.strip().upper()
            return "YES" in cleaned_response
        except Exception:
            return False

    def execute(self, parsed_data) -> str:
        # 组装提示词
        return TOKYO_STAR_COUNTER_OPEN_SKILL_PROMPT


class TokyoStarOnlineAddressModSkill(BaseSkill):
    """
    Skill 2: 东京之星银行Star One账户网上申请地址错误修改
    """
    name = "tokyo_star_online_address_modification"
    chinese_name = "东京之星银行Star One账户网上申请地址错误修改"

    def match(self, parsed_data: Dict[str, Any]) -> bool:
        chat_input = parsed_data.get("chat_input", "")
        context = parsed_data.get("context", "")
        full_text = f"用户输入: {chat_input}\n上下文历史: {context}"

        prompt = (
            "你是一个业务意图识别助手。请分析以下用户的输入和上下文，判断用户的意图是否符合“东京之星银行Star One账户网上申请信息修改”场景。\n\n"
            "【匹配条件】\n"
            "- 核心意图：客户在网上/在线申请了 Star One 账户后，发现填错了信息（如地址、邮箱、姓名、电话等），需要进行修改或变更。\n\n"
            "【排除条件】\n"
            "- 明确指出是通过“柜台”、“柜面”或“线下”渠道提交申请的信息修改。\n\n"
            f"【对话内容】\n{full_text}\n\n"
            "【输出要求】\n"
            "如果用户意图符合匹配条件，且不满足排除条件，请直接输出 \"YES\"；否则输出 \"NO\"。请勿包含任何其他多余的解释、标点或回复。"
        )

        try:
            response = self.call_llm(prompt)
            cleaned_response = response.strip().upper()
            return "YES" in cleaned_response
        except Exception:
            return False

    def execute(self, parsed_data) -> str:
        # 组装提示词
        return TOKYO_STAR_ONLINE_ADDRESS_MOD_SKILL_PROMPT


# ==================== 使用示例 ====================
if __name__ == "__main__":
    import os
    from openai import OpenAI

    API_KEY = os.getenv("SILICONFLOW_API_KEY", "sk-duhwosgxlixiqnoeremlimqgorstljququocpbyrkyfxwuih")
    BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    TOOL_MODEL = os.getenv("TOOL_MODEL", "Qwen/Qwen2.5-32B-Instruct")
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
        timeout=30.0  # 避免请求无限挂起
    )

    # 实例化各技能
    counter_open_skill = TokyoStarCounterOpenSkill(client, model=TOOL_MODEL)
    online_mod_skill = TokyoStarOnlineAddressModSkill(client, model=TOOL_MODEL)

    # 模拟输入
    test_data = {
        "chat_input": "请问如果我在网上申请Star One账户时邮箱填错，怎么修改？",
        "context": "",
        "session_state": {}
    }

    # 注意：运行此代码需要确保环境变量 LLM_API_KEY 与 LLM_BASE_URL 已正确配置，或者将上方常量替换为可用凭证。
    try:
        match_result = online_mod_skill.match(test_data)
        logger.info(f"Skill '{online_mod_skill.name}' 匹配结果: {match_result}")
    except Exception as e:
        logger.error(f"由于未配置真实 API 密钥，大模型请求未能成功执行：{e}")
