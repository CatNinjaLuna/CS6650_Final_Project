package aggregator;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;

/**
 * Manages active WebSocket sessions and broadcasts messages to all connected clients.
 *
 * Frontend clients connect to ws://localhost:8082/ws/results. Each connection is
 * tracked in a thread-safe set. When RedisSubscriber receives a result, it calls
 * broadcast() to fan out the JSON payload to every open session.
 */
@Component
public class WebSocketHandler extends TextWebSocketHandler {

  // Thread-safe set — multiple Redis listener threads may call broadcast() concurrently
  private final Set<WebSocketSession> sessions = new CopyOnWriteArraySet<>();

  /** Called when a frontend client opens a WebSocket connection. */
  @Override
  public void afterConnectionEstablished(WebSocketSession session) {
    sessions.add(session);
    System.out.println("Client connected: " + session.getId() + " | total=" + sessions.size());
  }

  /** Called when a frontend client disconnects (tab close, network drop, etc.). */
  @Override
  public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
    sessions.remove(session);
    System.out.println("Client disconnected: " + session.getId() + " | total=" + sessions.size());
  }

  /**
   * Sends a JSON string to all currently connected WebSocket sessions.
   * Skips closed sessions silently; logs send failures without crashing.
   *
   * @param json serialized SimResult payload from Redis
   */
  public void broadcast(String json) {
    TextMessage msg = new TextMessage(json);
    for (WebSocketSession s : sessions) {
      if (s.isOpen()) {
        try {
          s.sendMessage(msg);
        } catch (IOException e) {
          System.err.println("Failed to send to " + s.getId() + ": " + e.getMessage());
        }
      }
    }
  }
}