"""Debug script to find where APIConnectionError originates in stream_response."""
import asyncio
import os
import sys
import traceback as tb

os.environ.update({
    'OPENAI_API_KEY': 'sk-m',
    'EMBEDDING_API_KEY': 'sk-m',
    'EMBEDDING_BASE_URL': 'http://localhost:0',
    'EMBEDDING_MODEL': 'm',
})

from src.core.agent import CodingAgent
from tests.core.conftest import MockLLMBackend, MockUIProtocol
from src.session.store.memory_store import MessageStore
from src.memory import TaskContext
from src.core.events import TextDelta
import uuid


def main():
    a = CodingAgent(
        model_name='m', backend='openai', base_url='http://localhost:0',
        context_window=128000, api_key='sk-m', working_directory='.',
        load_file_memories=False, permission_mode='auto',
    )
    store = MessageStore()
    a.memory.set_message_store(store, 'test-session')
    a.llm = MockLLMBackend([('Hello!', None)])
    a.backend_name = 'mock'

    async def manual_test():
        user_input = 'hi'

        # Step 1: setup
        task_context = TaskContext(
            task_id=str(uuid.uuid4()),
            description=user_input,
            task_type='chat',
            key_concepts=[],
        )
        a.memory.set_task_context(task_context)
        a.memory.add_user_message(user_input)
        print('[OK] add_user_message', file=sys.stderr)

        # Step 2: build context
        context = a.context_builder.build_context(
            user_query=user_input, task_type='chat', language='python',
            plan_mode_state=a.plan_mode_state,
        )
        print(f'[OK] build_context: {len(context)} messages', file=sys.stderr)

        # Step 3: start_assistant_stream
        try:
            a.memory.start_assistant_stream(provider='mock', model='m')
            print('[OK] start_assistant_stream', file=sys.stderr)
        except Exception as e:
            print(f'[FAIL] start_assistant_stream: {e}', file=sys.stderr)
            tb.print_exc(file=sys.stderr)
            return

        # Step 4: LLM call
        try:
            llm_stream = a.llm.generate_provider_deltas_async(
                messages=context, tools=a._get_tools(), tool_choice='auto'
            )
            print(f'[OK] got llm_stream: {type(llm_stream).__name__}', file=sys.stderr)

            async for delta in llm_stream:
                print(f'  delta: text={delta.text_delta!r}, finish={delta.finish_reason}', file=sys.stderr)
                msg = a.memory.process_provider_delta(delta)
                if msg:
                    print(f'  finalized: {msg.content[:100] if msg.content else "(no content)"}', file=sys.stderr)
        except Exception as e:
            print(f'[FAIL] LLM streaming: {e}', file=sys.stderr)
            tb.print_exc(file=sys.stderr)

    asyncio.run(manual_test())


if __name__ == '__main__':
    main()
