//! Integration tests for model streaming using a mock SSE server.
///
/// These tests start a real HTTP server that speaks SSE, point the model
/// adapters at it, and verify the full streaming path end-to-end.
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use axum::body::Body;
use axum::http::StatusCode;
use axum::response::Response;
use axum::routing::post;
use axum::Router;
use tokio_util::sync::CancellationToken;

use op_core::events::{DeltaEvent, DeltaKind};
use op_core::model::openai::OpenAIModel;
use op_core::model::anthropic::AnthropicModel;
use op_core::model::{BaseModel, Message};

// ─── Helpers ───

/// Collect deltas emitted during a chat_stream call.
#[derive(Clone)]
struct DeltaCollector {
    deltas: Arc<Mutex<Vec<DeltaEvent>>>,
}

impl DeltaCollector {
    fn new() -> Self {
        Self {
            deltas: Arc::new(Mutex::new(Vec::new())),
        }
    }
    fn push(&self, event: DeltaEvent) {
        self.deltas.lock().unwrap().push(event);
    }
    fn events(&self) -> Vec<DeltaEvent> {
        self.deltas.lock().unwrap().clone()
    }
}

/// Start a mock server that returns the given SSE body and return its address.
async fn start_mock_sse_server(sse_body: &'static str) -> SocketAddr {
    let app = Router::new().route(
        "/{*path}",
        post(move || async move {
            Response::builder()
                .status(StatusCode::OK)
                .header("content-type", "text/event-stream")
                .header("cache-control", "no-cache")
                .body(Body::from(sse_body))
                .unwrap()
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

/// Start a mock server that returns an error status code.
async fn start_error_server(status: u16, body: &'static str) -> SocketAddr {
    let app = Router::new().route(
        "/{*path}",
        post(move || async move {
            Response::builder()
                .status(StatusCode::from_u16(status).unwrap())
                .header("content-type", "application/json")
                .body(Body::from(body))
                .unwrap()
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

fn simple_messages() -> Vec<Message> {
    vec![
        Message::System { content: "You are helpful.".to_string() },
        Message::User { content: "Say hello".to_string() },
    ]
}

// ─── OpenAI streaming tests ───

const OPENAI_SSE_SIMPLE: &str = "\
data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{\"content\":\" world\"},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\",\"index\":0}],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":2}}\n\n\
data: [DONE]\n\n";

#[tokio::test]
async fn test_openai_stream_text() {
    let addr = start_mock_sse_server(OPENAI_SSE_SIMPLE).await;
    let model = OpenAIModel::new(
        "gpt-4o".to_string(),
        "openai".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
        HashMap::new(),
    );

    let collector = DeltaCollector::new();
    let c = collector.clone();
    let cancel = CancellationToken::new();
    let turn = model
        .chat_stream(&simple_messages(), &[], &move |d| c.push(d), &cancel)
        .await
        .expect("chat_stream should succeed");

    assert_eq!(turn.text, "Hello world");
    assert_eq!(turn.input_tokens, 10);
    assert_eq!(turn.output_tokens, 2);
    assert!(turn.tool_calls.is_empty());

    let deltas = collector.events();
    let text_deltas: Vec<&str> = deltas
        .iter()
        .filter(|d| matches!(d.kind, DeltaKind::Text))
        .map(|d| d.text.as_str())
        .collect();
    assert_eq!(text_deltas, vec!["Hello", " world"]);
}

const OPENAI_SSE_TOOL_CALL: &str = "\
data: {\"choices\":[{\"delta\":{\"role\":\"assistant\",\"tool_calls\":[{\"index\":0,\"id\":\"call_abc\",\"type\":\"function\",\"function\":{\"name\":\"read_file\",\"arguments\":\"\"}}]},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"{\\\"pa\"}}]},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"th\\\":\\\"test.txt\\\"}\"}}]},\"index\":0}]}\n\n\
data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\",\"index\":0}],\"usage\":{\"prompt_tokens\":20,\"completion_tokens\":5}}\n\n\
data: [DONE]\n\n";

#[tokio::test]
async fn test_openai_stream_tool_call() {
    let addr = start_mock_sse_server(OPENAI_SSE_TOOL_CALL).await;
    let model = OpenAIModel::new(
        "gpt-4o".to_string(),
        "openai".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
        HashMap::new(),
    );

    let collector = DeltaCollector::new();
    let c = collector.clone();
    let cancel = CancellationToken::new();
    let turn = model
        .chat_stream(&simple_messages(), &[], &move |d| c.push(d), &cancel)
        .await
        .expect("chat_stream should succeed");

    assert_eq!(turn.tool_calls.len(), 1);
    assert_eq!(turn.tool_calls[0].id, "call_abc");
    assert_eq!(turn.tool_calls[0].name, "read_file");
    assert_eq!(turn.tool_calls[0].arguments, "{\"path\":\"test.txt\"}");

    let deltas = collector.events();
    let tool_start: Vec<&str> = deltas
        .iter()
        .filter(|d| matches!(d.kind, DeltaKind::ToolCallStart))
        .map(|d| d.text.as_str())
        .collect();
    assert_eq!(tool_start, vec!["read_file"]);
}

#[tokio::test]
async fn test_openai_stream_cancel() {
    // Use a server that delays - but we cancel immediately
    let addr = start_mock_sse_server(OPENAI_SSE_SIMPLE).await;
    let model = OpenAIModel::new(
        "gpt-4o".to_string(),
        "openai".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
        HashMap::new(),
    );

    let cancel = CancellationToken::new();
    cancel.cancel(); // Cancel before starting
    let result = model
        .chat_stream(&simple_messages(), &[], &|_| {}, &cancel)
        .await;

    assert!(result.is_err());
    assert!(result.unwrap_err().to_string().contains("Cancelled"));
}

// ─── Anthropic streaming tests ───

const ANTHROPIC_SSE_SIMPLE: &str = "\
event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_1\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[],\"usage\":{\"input_tokens\":25}}}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"Hello\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\" from Claude\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n\
event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"},\"usage\":{\"output_tokens\":4}}\n\n\
event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n";

#[tokio::test]
async fn test_anthropic_stream_text() {
    let addr = start_mock_sse_server(ANTHROPIC_SSE_SIMPLE).await;
    let model = AnthropicModel::new(
        "claude-sonnet-4-5".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
    );

    let collector = DeltaCollector::new();
    let c = collector.clone();
    let cancel = CancellationToken::new();
    let turn = model
        .chat_stream(&simple_messages(), &[], &move |d| c.push(d), &cancel)
        .await
        .expect("chat_stream should succeed");

    assert_eq!(turn.text, "Hello from Claude");
    assert_eq!(turn.input_tokens, 25);
    assert_eq!(turn.output_tokens, 4);
    assert!(turn.thinking.is_none());
    assert!(turn.tool_calls.is_empty());

    let deltas = collector.events();
    let text_deltas: Vec<&str> = deltas
        .iter()
        .filter(|d| matches!(d.kind, DeltaKind::Text))
        .map(|d| d.text.as_str())
        .collect();
    assert_eq!(text_deltas, vec!["Hello", " from Claude"]);
}

const ANTHROPIC_SSE_THINKING: &str = "\
event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_2\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[],\"usage\":{\"input_tokens\":30}}}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"thinking\",\"thinking\":\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"thinking_delta\",\"thinking\":\"Let me think...\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"text_delta\",\"text\":\"Here is my answer.\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":1}\n\n\
event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"},\"usage\":{\"output_tokens\":10}}\n\n\
event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n";

#[tokio::test]
async fn test_anthropic_stream_thinking() {
    let addr = start_mock_sse_server(ANTHROPIC_SSE_THINKING).await;
    let model = AnthropicModel::new(
        "claude-opus-4-6".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        Some("high".to_string()),
    );

    let collector = DeltaCollector::new();
    let c = collector.clone();
    let cancel = CancellationToken::new();
    let turn = model
        .chat_stream(&simple_messages(), &[], &move |d| c.push(d), &cancel)
        .await
        .expect("chat_stream should succeed");

    assert_eq!(turn.text, "Here is my answer.");
    assert_eq!(turn.thinking, Some("Let me think...".to_string()));
    assert_eq!(turn.input_tokens, 30);
    assert_eq!(turn.output_tokens, 10);

    let deltas = collector.events();
    let thinking_deltas: Vec<&str> = deltas
        .iter()
        .filter(|d| matches!(d.kind, DeltaKind::Thinking))
        .map(|d| d.text.as_str())
        .collect();
    assert_eq!(thinking_deltas, vec!["Let me think..."]);
}

const ANTHROPIC_SSE_TOOL: &str = "\
event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_3\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[],\"usage\":{\"input_tokens\":15}}}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"tool_use\",\"id\":\"toolu_1\",\"name\":\"read_file\",\"input\":{}}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"path\\\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\":\\\"test.txt\\\"}\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n\
event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"tool_use\"},\"usage\":{\"output_tokens\":8}}\n\n\
event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n";

#[tokio::test]
async fn test_anthropic_stream_tool_call() {
    let addr = start_mock_sse_server(ANTHROPIC_SSE_TOOL).await;
    let model = AnthropicModel::new(
        "claude-sonnet-4-5".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
    );

    let collector = DeltaCollector::new();
    let c = collector.clone();
    let cancel = CancellationToken::new();
    let turn = model
        .chat_stream(&simple_messages(), &[], &move |d| c.push(d), &cancel)
        .await
        .expect("chat_stream should succeed");

    assert_eq!(turn.tool_calls.len(), 1);
    assert_eq!(turn.tool_calls[0].id, "toolu_1");
    assert_eq!(turn.tool_calls[0].name, "read_file");
    assert_eq!(turn.tool_calls[0].arguments, "{\"path\":\"test.txt\"}");
}

#[tokio::test]
async fn test_anthropic_stream_cancel() {
    let addr = start_mock_sse_server(ANTHROPIC_SSE_SIMPLE).await;
    let model = AnthropicModel::new(
        "claude-sonnet-4-5".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
    );

    let cancel = CancellationToken::new();
    cancel.cancel();
    let result = model
        .chat_stream(&simple_messages(), &[], &|_| {}, &cancel)
        .await;

    assert!(result.is_err());
    assert!(result.unwrap_err().to_string().contains("Cancelled"));
}

// ─── Non-streaming chat() tests ───

#[tokio::test]
async fn test_openai_chat_non_streaming() {
    let addr = start_mock_sse_server(OPENAI_SSE_SIMPLE).await;
    let model = OpenAIModel::new(
        "gpt-4o".to_string(),
        "openai".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
        HashMap::new(),
    );

    // chat() should internally call chat_stream with no-op callback
    let turn = model.chat(&simple_messages(), &[]).await.expect("chat should succeed");
    assert_eq!(turn.text, "Hello world");
    assert_eq!(turn.input_tokens, 10);
}

#[tokio::test]
async fn test_anthropic_chat_non_streaming() {
    let addr = start_mock_sse_server(ANTHROPIC_SSE_SIMPLE).await;
    let model = AnthropicModel::new(
        "claude-sonnet-4-5".to_string(),
        format!("http://{addr}"),
        "test-key".to_string(),
        None,
    );

    let turn = model.chat(&simple_messages(), &[]).await.expect("chat should succeed");
    assert_eq!(turn.text, "Hello from Claude");
    assert_eq!(turn.input_tokens, 25);
}

// ─── Error handling tests ───

#[tokio::test]
async fn test_openai_http_error() {
    let addr = start_error_server(
        401,
        r#"{"error":{"message":"Invalid API key","type":"invalid_request_error"}}"#,
    ).await;
    let model = OpenAIModel::new(
        "gpt-4o".to_string(),
        "openai".to_string(),
        format!("http://{addr}"),
        "bad-key".to_string(),
        None,
        HashMap::new(),
    );

    let cancel = CancellationToken::new();
    let result = model
        .chat_stream(&simple_messages(), &[], &|_| {}, &cancel)
        .await;

    assert!(result.is_err(), "should fail with HTTP error");
}

#[tokio::test]
async fn test_anthropic_http_error() {
    let addr = start_error_server(
        401,
        r#"{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}"#,
    ).await;
    let model = AnthropicModel::new(
        "claude-sonnet-4-5".to_string(),
        format!("http://{addr}"),
        "bad-key".to_string(),
        None,
    );

    let cancel = CancellationToken::new();
    let result = model
        .chat_stream(&simple_messages(), &[], &|_| {}, &cancel)
        .await;

    assert!(result.is_err(), "should fail with HTTP error");
}

// ─── Full solve() integration test ───

#[tokio::test]
async fn test_solve_with_mock_anthropic() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    let addr = start_mock_sse_server(ANTHROPIC_SSE_SIMPLE).await;

    #[derive(Debug, Clone)]
    enum Ev {
        Trace(String),
        Delta(DeltaEvent),
        Step(StepEvent),
        Complete(String),
        Error(String),
    }

    struct TestEmitter {
        events: Arc<Mutex<Vec<Ev>>>,
    }
    impl SolveEmitter for TestEmitter {
        fn emit_trace(&self, message: &str) {
            self.events.lock().unwrap().push(Ev::Trace(message.to_string()));
        }
        fn emit_delta(&self, event: DeltaEvent) {
            self.events.lock().unwrap().push(Ev::Delta(event));
        }
        fn emit_step(&self, event: StepEvent) {
            self.events.lock().unwrap().push(Ev::Step(event));
        }
        fn emit_complete(&self, result: &str) {
            self.events.lock().unwrap().push(Ev::Complete(result.to_string()));
        }
        fn emit_error(&self, message: &str) {
            self.events.lock().unwrap().push(Ev::Error(message.to_string()));
        }
    }

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitter = TestEmitter { events: events.clone() };

    let cfg = AgentConfig {
        provider: "anthropic".into(),
        model: "claude-sonnet-4-5".into(),
        anthropic_api_key: Some("test-key".into()),
        anthropic_base_url: format!("http://{addr}"),
        demo: false,
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("Hello", &cfg, &emitter, cancel).await;

    let recorded = events.lock().unwrap().clone();

    // Should have a trace
    assert!(
        recorded.iter().any(|e| matches!(e, Ev::Trace(m) if m.contains("anthropic"))),
        "should have a trace mentioning anthropic"
    );

    // Should have text deltas
    let text_content: String = recorded
        .iter()
        .filter_map(|e| match e {
            Ev::Delta(d) if matches!(d.kind, DeltaKind::Text) => Some(d.text.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(text_content, "Hello from Claude");

    // Should have a step
    assert!(
        recorded.iter().any(|e| matches!(e, Ev::Step(s) if s.is_final && s.tokens.input_tokens == 25)),
        "should have a final step with correct token count"
    );

    // Should have complete with the full text
    assert!(
        recorded.iter().any(|e| matches!(e, Ev::Complete(t) if t == "Hello from Claude")),
        "should complete with full text"
    );

    // Should NOT have an error
    assert!(
        !recorded.iter().any(|e| matches!(e, Ev::Error(_))),
        "should not have any errors"
    );
}

#[tokio::test]
async fn test_solve_with_mock_openai() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    let addr = start_mock_sse_server(OPENAI_SSE_SIMPLE).await;

    #[derive(Debug, Clone)]
    #[allow(dead_code)]
    enum Ev2 {
        Trace(String),
        Delta(DeltaEvent),
        Step(StepEvent),
        Complete(String),
        Error(String),
    }

    struct TestEmitter2 {
        events: Arc<Mutex<Vec<Ev2>>>,
    }
    impl SolveEmitter for TestEmitter2 {
        fn emit_trace(&self, message: &str) {
            self.events.lock().unwrap().push(Ev2::Trace(message.to_string()));
        }
        fn emit_delta(&self, event: DeltaEvent) {
            self.events.lock().unwrap().push(Ev2::Delta(event));
        }
        fn emit_step(&self, event: StepEvent) {
            self.events.lock().unwrap().push(Ev2::Step(event));
        }
        fn emit_complete(&self, result: &str) {
            self.events.lock().unwrap().push(Ev2::Complete(result.to_string()));
        }
        fn emit_error(&self, message: &str) {
            self.events.lock().unwrap().push(Ev2::Error(message.to_string()));
        }
    }

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitter = TestEmitter2 { events: events.clone() };

    let cfg = AgentConfig {
        provider: "openai".into(),
        model: "gpt-4o".into(),
        openai_api_key: Some("test-key".into()),
        openai_base_url: format!("http://{addr}"),
        base_url: format!("http://{addr}"),
        demo: false,
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("Hello", &cfg, &emitter, cancel).await;

    let recorded = events.lock().unwrap().clone();

    // Should have a trace mentioning openai
    assert!(
        recorded.iter().any(|e| matches!(e, Ev2::Trace(m) if m.contains("openai"))),
        "should have a trace mentioning openai, got: {:?}",
        recorded.iter().filter_map(|e| match e { Ev2::Trace(m) => Some(m.clone()), _ => None }).collect::<Vec<_>>()
    );

    // Should have text deltas that spell "Hello world"
    let text_content: String = recorded
        .iter()
        .filter_map(|e| match e {
            Ev2::Delta(d) if matches!(d.kind, DeltaKind::Text) => Some(d.text.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(text_content, "Hello world");

    // Should have a step with correct tokens
    assert!(
        recorded.iter().any(|e| matches!(e, Ev2::Step(s) if s.is_final && s.tokens.input_tokens == 10)),
        "should have a final step with 10 input tokens"
    );

    // Should complete with the full text
    assert!(
        recorded.iter().any(|e| matches!(e, Ev2::Complete(t) if t == "Hello world")),
        "should complete with 'Hello world'"
    );

    // No errors
    assert!(
        !recorded.iter().any(|e| matches!(e, Ev2::Error(_))),
        "should not have any errors"
    );
}

#[tokio::test]
async fn test_solve_http_error_emits_error() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    let addr = start_error_server(
        401,
        r#"{"error":{"message":"Invalid API key"}}"#,
    ).await;

    struct ErrorEmitter {
        errors: Arc<Mutex<Vec<String>>>,
    }
    impl SolveEmitter for ErrorEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, _: DeltaEvent) {}
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, _: &str) {}
        fn emit_error(&self, msg: &str) {
            self.errors.lock().unwrap().push(msg.to_string());
        }
    }

    let errors = Arc::new(Mutex::new(Vec::new()));
    let emitter = ErrorEmitter { errors: errors.clone() };

    let cfg = AgentConfig {
        provider: "openai".into(),
        model: "gpt-4o".into(),
        openai_api_key: Some("bad-key".into()),
        openai_base_url: format!("http://{addr}"),
        base_url: format!("http://{addr}"),
        demo: false,
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("Test", &cfg, &emitter, cancel).await;

    let recorded = errors.lock().unwrap().clone();
    assert!(
        !recorded.is_empty(),
        "should emit an error for HTTP 401"
    );
}

#[tokio::test]
async fn test_solve_cancel_emits_cancelled() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    // Use a server that returns data but we cancel before processing
    let addr = start_mock_sse_server(ANTHROPIC_SSE_SIMPLE).await;

    struct CancelEmitter {
        events: Arc<Mutex<Vec<String>>>,
    }
    impl SolveEmitter for CancelEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, _: DeltaEvent) {}
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, _: &str) {}
        fn emit_error(&self, msg: &str) {
            self.events.lock().unwrap().push(msg.to_string());
        }
    }

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitter = CancelEmitter { events: events.clone() };

    let cfg = AgentConfig {
        provider: "anthropic".into(),
        model: "claude-sonnet-4-5".into(),
        anthropic_api_key: Some("test-key".into()),
        anthropic_base_url: format!("http://{addr}"),
        demo: false,
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    cancel.cancel(); // Cancel immediately
    solve("Test", &cfg, &emitter, cancel).await;

    let recorded = events.lock().unwrap().clone();
    assert!(
        recorded.iter().any(|e| e.contains("Cancelled")),
        "should emit Cancelled error, got: {:?}",
        recorded
    );
}

#[tokio::test]
async fn test_solve_demo_mode_bypasses_llm() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    struct TestEmitter {
        events: Arc<Mutex<Vec<String>>>,
    }
    impl SolveEmitter for TestEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, _: DeltaEvent) {}
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, result: &str) {
            self.events.lock().unwrap().push(result.to_string());
        }
        fn emit_error(&self, msg: &str) {
            self.events.lock().unwrap().push(format!("ERROR: {msg}"));
        }
    }

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitter = TestEmitter { events: events.clone() };

    let cfg = AgentConfig {
        demo: true,
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("Test objective", &cfg, &emitter, cancel).await;

    let recorded = events.lock().unwrap().clone();
    assert!(
        recorded.iter().any(|r| r.contains("Test objective")),
        "demo mode should echo the objective"
    );
}

#[tokio::test]
async fn test_solve_missing_key_emits_error() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    struct TestEmitter {
        errors: Arc<Mutex<Vec<String>>>,
    }
    impl SolveEmitter for TestEmitter {
        fn emit_trace(&self, _: &str) {}
        fn emit_delta(&self, _: DeltaEvent) {}
        fn emit_step(&self, _: StepEvent) {}
        fn emit_complete(&self, _: &str) {}
        fn emit_error(&self, msg: &str) {
            self.errors.lock().unwrap().push(msg.to_string());
        }
    }

    let errors = Arc::new(Mutex::new(Vec::new()));
    let emitter = TestEmitter { errors: errors.clone() };

    let cfg = AgentConfig {
        provider: "openai".into(),
        model: "gpt-4o".into(),
        demo: false,
        // No API key set
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("Test", &cfg, &emitter, cancel).await;

    let recorded = errors.lock().unwrap().clone();
    assert!(
        recorded.iter().any(|e| e.contains("API key")),
        "should emit error about missing API key, got: {:?}",
        recorded
    );
}

// ─── Multi-step agentic loop integration test ───
//
// Uses a stateful mock server that returns a tool call on the first request,
// then a final text answer on the second. This validates the full loop:
// model → tool call → tool execution → model → final answer.

/// SSE body for an Anthropic response that requests `list_files`.
const ANTHROPIC_SSE_TOOL_LIST: &str = "\
event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_loop1\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[],\"usage\":{\"input_tokens\":50}}}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"Let me list the files.\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"tool_use\",\"id\":\"toolu_loop1\",\"name\":\"list_files\",\"input\":{}}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{}\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":1}\n\n\
event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"tool_use\"},\"usage\":{\"output_tokens\":12}}\n\n\
event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n";

/// SSE body for the follow-up Anthropic response (final text answer after tool result).
const ANTHROPIC_SSE_FINAL_ANSWER: &str = "\
event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"id\":\"msg_loop2\",\"type\":\"message\",\"role\":\"assistant\",\"content\":[],\"usage\":{\"input_tokens\":80}}}\n\n\
event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n\
event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"I found the files. Here is the answer.\"}}\n\n\
event: content_block_stop\ndata: {\"type\":\"content_block_stop\",\"index\":0}\n\n\
event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"},\"usage\":{\"output_tokens\":10}}\n\n\
event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n";

/// Start a stateful mock server that returns different SSE bodies on successive calls.
async fn start_stateful_mock_server(responses: Vec<&'static str>) -> SocketAddr {
    let counter = Arc::new(Mutex::new(0usize));
    let responses = Arc::new(responses);

    let app = Router::new().route(
        "/{*path}",
        post(move || {
            let counter = counter.clone();
            let responses = responses.clone();
            async move {
                let mut idx = counter.lock().unwrap();
                let body = if *idx < responses.len() {
                    responses[*idx]
                } else {
                    // Fallback: return the last response
                    responses.last().unwrap()
                };
                *idx += 1;
                Response::builder()
                    .status(StatusCode::OK)
                    .header("content-type", "text/event-stream")
                    .header("cache-control", "no-cache")
                    .body(Body::from(body))
                    .unwrap()
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    addr
}

#[tokio::test]
async fn test_solve_multi_step_agentic_loop() {
    use op_core::config::AgentConfig;
    use op_core::engine::{solve, SolveEmitter};
    use op_core::events::StepEvent;

    // Mock server: first call → tool call, second call → final answer
    let addr = start_stateful_mock_server(vec![
        ANTHROPIC_SSE_TOOL_LIST,
        ANTHROPIC_SSE_FINAL_ANSWER,
    ]).await;

    #[derive(Debug, Clone)]
    #[allow(dead_code)]
    enum Ev3 {
        Trace(String),
        Delta(DeltaEvent),
        Step(StepEvent),
        Complete(String),
        Error(String),
    }

    struct TestEmitter3 {
        events: Arc<Mutex<Vec<Ev3>>>,
    }
    impl SolveEmitter for TestEmitter3 {
        fn emit_trace(&self, message: &str) {
            self.events.lock().unwrap().push(Ev3::Trace(message.to_string()));
        }
        fn emit_delta(&self, event: DeltaEvent) {
            self.events.lock().unwrap().push(Ev3::Delta(event));
        }
        fn emit_step(&self, event: StepEvent) {
            self.events.lock().unwrap().push(Ev3::Step(event));
        }
        fn emit_complete(&self, result: &str) {
            self.events.lock().unwrap().push(Ev3::Complete(result.to_string()));
        }
        fn emit_error(&self, message: &str) {
            self.events.lock().unwrap().push(Ev3::Error(message.to_string()));
        }
    }

    let events = Arc::new(Mutex::new(Vec::new()));
    let emitter = TestEmitter3 { events: events.clone() };

    // Use a temp dir as workspace so list_files has something to work with
    let tmp = tempfile::TempDir::new().unwrap();
    // Create a test file so list_files finds something
    std::fs::write(tmp.path().join("hello.txt"), "world").unwrap();

    let cfg = AgentConfig {
        provider: "anthropic".into(),
        model: "claude-sonnet-4-5".into(),
        anthropic_api_key: Some("test-key".into()),
        anthropic_base_url: format!("http://{addr}"),
        demo: false,
        workspace: tmp.path().to_path_buf(),
        ..Default::default()
    };

    let cancel = CancellationToken::new();
    solve("List the files in this directory", &cfg, &emitter, cancel).await;

    let recorded = events.lock().unwrap().clone();

    // Verify we got TWO step events (one non-final for tool call, one final for answer)
    let steps: Vec<&StepEvent> = recorded
        .iter()
        .filter_map(|e| match e {
            Ev3::Step(s) => Some(s),
            _ => None,
        })
        .collect();
    assert!(
        steps.len() >= 2,
        "expected at least 2 steps (tool call + final answer), got {}: {:?}",
        steps.len(),
        steps
    );

    // First step should be non-final (has tool call)
    assert!(
        !steps[0].is_final,
        "first step should be non-final (tool call)"
    );
    assert_eq!(
        steps[0].tool_name.as_deref(),
        Some("list_files"),
        "first step should show list_files tool"
    );

    // Last step should be final
    assert!(
        steps.last().unwrap().is_final,
        "last step should be final"
    );

    // Should have tool execution trace
    let has_tool_trace = recorded.iter().any(|e| matches!(e, Ev3::Trace(m) if m.contains("list_files")));
    assert!(has_tool_trace, "should have a trace mentioning list_files tool execution");

    // Should have text deltas from both steps
    let text_content: String = recorded
        .iter()
        .filter_map(|e| match e {
            Ev3::Delta(d) if matches!(d.kind, DeltaKind::Text) => Some(d.text.clone()),
            _ => None,
        })
        .collect();
    assert!(
        text_content.contains("Let me list the files"),
        "should have text from step 1, got: {text_content}"
    );
    assert!(
        text_content.contains("Here is the answer"),
        "should have text from step 2, got: {text_content}"
    );

    // Should complete with the final answer text
    assert!(
        recorded.iter().any(|e| matches!(e, Ev3::Complete(t) if t.contains("Here is the answer"))),
        "should complete with the final answer"
    );

    // Should NOT have errors
    let errors: Vec<&String> = recorded
        .iter()
        .filter_map(|e| match e {
            Ev3::Error(m) => Some(m),
            _ => None,
        })
        .collect();
    assert!(
        errors.is_empty(),
        "should not have any errors, got: {:?}",
        errors
    );
}
