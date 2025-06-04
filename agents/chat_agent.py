import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
import json
from typing import Generator

class ChatAgent:
    def __init__(self, model_name="gpt-3.5-turbo"):
        """Initialize the ChatAgent with specified model."""
        self.model = ChatOpenAI(model_name=model_name, temperature=0.7, streaming=True)
        # Define required fields (these must be filled) - removed 'name' as it's not critical
        self.required_fields = ["city", "days", "budget", "people", "kids", "health", "hobbies"]
        # Optional fields that help with planning but aren't required to proceed
        self.optional_fields = ["name", "start_date", "specificRequirements"]
        # Define all fields, including optional ones
        self.all_fields = self.required_fields + self.optional_fields
        self.conversation_history = []
        
    def _init_system_message(self):
        """Initialize system message for the conversation."""
        return SystemMessage(content="""
        You are a helpful travel assistant. Your job is to collect information about the user's travel plans.
        Be friendly, conversational, and help the user plan their trip. Collect all necessary information.
        Also pay attention to any specific requirements the traveler mentions, such as accessibility needs,
        food restrictions, special interests, or any constraints that might affect their trip.
        """)
        
    def collect_info(self, user_input: str, state: dict = None) -> dict:
        """Check for missing information and ask user questions to complete the required information."""
        if state is None:
            state = {}
        
        # Initialize conversation if it's empty
        if not self.conversation_history:
            self.conversation_history.append(self._init_system_message())
        
        # Merge new inputs into state
        if user_input and user_input.strip():
            new_info = self.extract_info_from_message(user_input)
            for field, value in new_info.items():
                if value:
                    state[field] = value
                    print(f"Updated state: {field} = {value}")  # Debug log
        
        # Add user input to conversation if not empty
        if user_input and user_input.strip():
            self.conversation_history.append(HumanMessage(content=user_input))
        
        # Check completion - be more flexible about what constitutes "complete"
        missing_required = [f for f in self.required_fields if not state.get(f)]
        
        # Special handling for start_date - "not decided" is acceptable
        start_date = state.get("start_date", "")
        if start_date == "not decided":
            state["start_date"] = "not decided"  # Ensure it's in state
        
        # Consider complete if we have the core travel info
        core_fields = ["city", "days", "budget", "people"]
        has_core_info = all(state.get(f) for f in core_fields)
        
        # More flexible completion - if we have core info and most other fields
        is_complete = has_core_info and len(missing_required) <= 2
        
        # Get AI response based on current state and conversation history
        messages = self.conversation_history.copy()
        messages.append(SystemMessage(content=f"""
        Current state: {json.dumps(state, ensure_ascii=False)}
        Required fields: {json.dumps(self.required_fields, ensure_ascii=False)}
        Missing fields: {json.dumps(missing_required, ensure_ascii=False)}
        Core travel info complete: {has_core_info}
        Ready to proceed: {is_complete}
        
        Please help the user complete the missing information in a natural way.
        Remember to acknowledge information that has already been provided.
        Tell the user that they can write "not decided" for the start date if they don't have a specific date in mind.
        Also pay attention to any specific requirements they mention and reflect these in your responses.
        
        If the user has provided the core travel information (city, days, budget, people), 
        you can proceed even if some optional details are missing.
        """))
        
        try:
            response = self.model.stream(messages)
            return {
                "stream": response,
                "missing_fields": missing_required,
                "complete": is_complete,
                "state": state.copy()
            }
        except Exception as e:
            print(f"Error getting AI response: {e}")
            return {
                "stream": None,
                "missing_fields": missing_required,
                "complete": False,
                "state": state.copy(),
                "error": str(e)
            }
    
    def interact_with_user(self, message: str, state: dict = None) -> Generator:
        """Process user message and generate a streaming response."""
        if state is None:
            state = {}
            
        # Add user message to conversation
        self.conversation_history.append(HumanMessage(content=message))
        
        # Generate streaming response based on the conversation history
        try:
            return self.model.stream(self.conversation_history)
        except Exception as e:
            print(f"Error in interact_with_user: {e}")
            return None
    
    def extract_info_from_message(self, message: str) -> dict:
        """Use LLM to extract structured travel information from user message."""
        system_prompt = f"""Extract the following travel information from the user's message and return JSON.
        Carefully analyze the message to understand both explicit and implicit information.
        
        For example, if the user says "without kids" or "no children", set "kids" to "no".
        If they mention "all adults", also set "kids" to "no".
        If they mention family with children, set "kids" to "yes".
        The people field should be an integer.
        Specifically, if the user gives a start date, set "start_date" in YYYY-MM-DD format string. Otherwise, set "start_date" to "not decided".
        Pay attention to negations and context. Don't just look for keywords, understand the meaning.
        
        IMPORTANT: Also extract any specific requirements, constraints, or special requests the user mentions. 
        This includes but is not limited to:
        - Accessibility needs (e.g., wheelchair access, limited mobility)
        - Food restrictions or dietary preferences
        - Special interests or experiences they want to have
        - Particular constraints (e.g., fear of heights, need quiet accommodations)
        - Any important preferences not covered by other fields
        
        Return the following JSON structure:
        {{
        {', '.join([f'"{field}": ""' for field in self.all_fields])}
        }}
        
        For required fields, if any information is missing or unclear, leave it as an empty string.
        For specificRequirements, capture any important preferences or constraints mentioned by the user.
        """
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=message)
        ]

        try:
            llm_response = self.model.invoke(messages)
            extracted_info = json.loads(llm_response.content)

            # Only update fields that have non-empty values
            filtered_info = {}
            for field in self.all_fields:
                value = extracted_info.get(field, "")
                if value:  # Only include non-empty values
                    filtered_info[field] = value

            return filtered_info 
        except Exception as e:
            print("Error parsing LLM output:", e)
            return {}
        

    