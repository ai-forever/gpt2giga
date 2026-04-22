"""Responses API v2 history-repair helpers."""

from typing import Any, Dict, List, Optional


class ResponsesV2HistoryRepairMixin:
    """Repair client-supplied Responses history before message assembly."""

    def _extract_response_v2_function_call(
        self,
        item: Dict[str, Any],
    ) -> tuple[Optional[str], Optional[str]]:
        item_type = item.get("type")
        if item_type == "function_call":
            name = item.get("name")
            call_id = item.get("call_id") or item.get("id")
            if isinstance(name, str) and name:
                return name, str(call_id) if call_id else None

        if item.get("role") != "assistant":
            return None, None

        function_call = item.get("function_call")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            call_id = (
                item.get("tools_state_id")
                or item.get("tool_state_id")
                or item.get("tool_call_id")
                or item.get("call_id")
                or item.get("id")
            )
            if isinstance(name, str) and name:
                return name, str(call_id) if call_id else None

        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if not isinstance(name, str) or not name:
                    continue
                call_id = (
                    tool_call.get("id")
                    or item.get("tools_state_id")
                    or item.get("tool_state_id")
                    or item.get("call_id")
                    or item.get("id")
                )
                return name, str(call_id) if call_id else None

        return None, None

    @staticmethod
    def _is_response_v2_function_result_item(
        item: Dict[str, Any],
        pending_function_name: Optional[str],
        pending_call_id: Optional[str],
    ) -> bool:
        item_type = item.get("type")
        if item_type == "function_call_output":
            call_id = item.get("call_id") or item.get("id")
            if pending_call_id and call_id:
                return str(call_id) == pending_call_id
            name = item.get("name")
            if pending_function_name and isinstance(name, str) and name:
                return name == pending_function_name
            return True

        if item.get("role") != "tool":
            return False

        call_id = (
            item.get("tool_call_id")
            or item.get("tools_state_id")
            or item.get("tool_state_id")
            or item.get("call_id")
            or item.get("id")
        )
        if pending_call_id and call_id:
            return str(call_id) == pending_call_id

        name = item.get("name")
        if pending_function_name and isinstance(name, str) and name:
            return name == pending_function_name
        return True

    def _build_missing_response_v2_tool_result_item(
        self,
        function_name: str,
        call_id: Optional[str],
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {
            "role": "tool",
            "name": function_name,
            "content": self._build_missing_function_result_payload(),
        }
        if call_id:
            item["tool_call_id"] = call_id
        return item

    def _repair_response_v2_input_history(self, input_: Any) -> Any:
        if not isinstance(input_, list):
            return input_

        repaired_items: List[Any] = []
        pending_function_name: Optional[str] = None
        pending_call_id: Optional[str] = None

        for item in input_:
            current_item = item.copy() if isinstance(item, dict) else item

            if pending_function_name is not None:
                if isinstance(
                    current_item,
                    dict,
                ) and self._is_response_v2_function_result_item(
                    current_item,
                    pending_function_name,
                    pending_call_id,
                ):
                    if current_item.get("role") == "tool":
                        if not current_item.get("name"):
                            current_item["name"] = pending_function_name
                        if pending_call_id and not current_item.get("tool_call_id"):
                            current_item["tool_call_id"] = pending_call_id
                    elif current_item.get("type") == "function_call_output":
                        if not current_item.get("name"):
                            current_item["name"] = pending_function_name
                        if pending_call_id and not current_item.get("call_id"):
                            current_item["call_id"] = pending_call_id
                    pending_function_name = None
                    pending_call_id = None
                else:
                    repaired_items.append(
                        self._build_missing_response_v2_tool_result_item(
                            pending_function_name,
                            pending_call_id,
                        )
                    )
                    self.logger.warning(
                        "Inserted synthetic tool result for dangling Responses API "
                        f"function call '{pending_function_name}'"
                    )
                    pending_function_name = None
                    pending_call_id = None

            repaired_items.append(current_item)

            if isinstance(current_item, dict):
                next_function_name, next_call_id = (
                    self._extract_response_v2_function_call(current_item)
                )
                if next_function_name:
                    pending_function_name = next_function_name
                    pending_call_id = next_call_id

        if pending_function_name is not None:
            repaired_items.append(
                self._build_missing_response_v2_tool_result_item(
                    pending_function_name,
                    pending_call_id,
                )
            )
            self.logger.warning(
                "Inserted synthetic tool result for trailing Responses API "
                f"function call '{pending_function_name}'"
            )

        return repaired_items
