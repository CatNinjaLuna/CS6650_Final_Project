package aggregator;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * Registers the WebSocket endpoint that frontend clients connect to.
 *
 * Endpoint: ws://localhost:8082/ws/results
 * CORS:     setAllowedOrigins("*") — open for local dev; restrict in production.
 *
 * The frontend (Wenxuan's React app) connects here to receive live SimResult
 * updates pushed from Isaac Sim via worker3 → Redis → aggregator → WebSocket.
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

  private final WebSocketHandler wsHandler;

  public WebSocketConfig(WebSocketHandler wsHandler) {
    this.wsHandler = wsHandler;
  }

  @Override
  public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
    registry.addHandler(wsHandler, "/ws/results").setAllowedOrigins("*");
  }
}