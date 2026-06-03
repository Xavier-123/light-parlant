tools = [
    {
        "type": "function",
        "function": {
            "name": "refuse_to_answer",
            "description": "策略 1：拒绝回答。适用场景：涉及机密、超出开户范围、存在安全或合规风险、知识库内容不足等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：合规禁止类问题、安全风险规避、知识库内容不足"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "高关联知识ID列表，无则填空数组"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "填写决策理由（分析意图与筛选逻辑）"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "user_terminate_consultation",
            "description": "策略 2：用户主动终止咨询。适用场景：意图状态为「放弃办理」或用户明确提出结束咨询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：用户主动提出结束、用户回避问题、用户切换话题"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关联知识ID列表，无则填空数组"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_or_follow_up",
            "description": "策略 3：确认 / 追问。适用场景：关键信息缺失，且状态非办结或放弃，需引导用户补充单项信息。限制：单次仅能追问一个问题，禁止多问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：开户资质（若用户国籍、办理网点信息缺失，需逐项追问）、开户所需资料（若用户国籍、办理网点信息缺失需追问；非日本籍用户，额外追问是否为永住者）、开户流程（办理网点不明、非特定投资账户类型时，需核实确认）、密码相关"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关联知识ID列表，无则填空数组"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "suggested_question": {
                        "type": "string",
                        "description": "追问的问题（单次仅写一个问题）"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning", "suggested_question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "direct_answer",
            "description": "策略 4：直接作答。适用场景：用户问题清晰、信息完整，且知识库存在高度匹配的内容，可直接输出。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：常规问题完整解答、多问题拆分解答、产品 / 服务推荐、操作指引说明、告知资质不符、告知符合开户条件、用户主动要求转接人工"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "匹配解答的全部高度关联知识ID"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "repeat_explanation",
            "description": "策略 5：重复说明。适用场景：用户重复提问、不理解表达、要求更换解释或内容复杂需要简化重新说明。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：用户表示无法理解、用户重复提问、内容复杂需简化、重点内容强化"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关联知识ID列表"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "greeting_or_transition",
            "description": "策略 6：问候 / 话题过渡。适用场景：用户发起基础问候、表达情绪不满、闲聊，或者用于平稳衔接过渡业务对话。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：简单问候回应、安抚负面情绪、用户表达感谢、闲聊话题应对、用户表达不满"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关联知识ID列表，无则填空数组"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "problem_solved",
            "description": "策略 7：问题已解决。适用场景：意图状态为「处理完成」，用户明确表达致谢或问题解决，用于对话自然收尾。",
            "parameters": {
                "type": "object",
                "properties": {
                    "second_layer_strategy": {
                        "type": "string",
                        "description": "第二层细化策略。可选：用户明确表示问题解决、用户表达感谢、长时间无回复且问题办结、对话目标达成、用户主动提出结束"
                    },
                    "selected_candidate_id": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关联知识ID列表，无则填空数组"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "决策理由"
                    },
                    "additional_guidance": {
                        "type": "string",
                        "description": "补充提示信息，无则留空"
                    }
                },
                "required": ["second_layer_strategy", "selected_candidate_id", "reasoning"]
            }
        }
    }
]
