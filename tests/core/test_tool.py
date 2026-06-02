from aaosa.core.tool import MAX_TOOL_ROUNDS, ToolDef


def search_docs(query: str) -> str:
    return f"Résultat pour : {query}"


def make_tool() -> ToolDef:
    return ToolDef(
        name="search_docs",
        description="Recherche dans la documentation",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        fn=search_docs,
    )


class TestToolDef:
    def test_tooldef_creation(self):
        tool = make_tool()
        assert tool.name == "search_docs"
        assert tool.description == "Recherche dans la documentation"
        assert tool.parameters["type"] == "object"
        assert callable(tool.fn)

    def test_tooldef_to_openai(self):
        tool = make_tool()
        spec = tool.to_openai()
        assert spec == {
            "type": "function",
            "function": {
                "name": "search_docs",
                "description": "Recherche dans la documentation",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }

    def test_tooldef_fn_called(self):
        tool = make_tool()
        assert tool.fn(query="x") == "Résultat pour : x"

    def test_max_tool_rounds_constant(self):
        assert MAX_TOOL_ROUNDS == 20
