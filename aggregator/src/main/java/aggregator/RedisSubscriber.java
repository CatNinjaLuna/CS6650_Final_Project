package aggregator;

import org.springframework.data.redis.connection.Message;
import org.springframework.data.redis.connection.MessageListener;
import org.springframework.stereotype.Component;

/**
 * Listens on the Redis pub/sub channel "roboparam:results".
 *
 * worker3 publishes a SimResult JSON string to this channel after each Isaac Sim job.
 * This subscriber receives the message and immediately delegates to WebSocketHandler
 * to fan it out to all connected frontend clients.
 *
 * Registered as a listener in RedisConfig via RedisMessageListenerContainer.
 */
@Component
public class RedisSubscriber implements MessageListener {

  private final WebSocketHandler wsHandler;

  public RedisSubscriber(WebSocketHandler wsHandler) {
    this.wsHandler = wsHandler;
  }

  /**
   * Invoked by Spring's Redis listener container when a message arrives on the channel.
   *
   * @param message raw Redis message; body contains the JSON string published by worker3
   * @param pattern the channel pattern that matched (roboparam:results)
   */
  @Override
  public void onMessage(Message message, byte[] pattern) {
    String json = new String(message.getBody());
    System.out.println("Redis received: " + json);
    wsHandler.broadcast(json);
  }
}