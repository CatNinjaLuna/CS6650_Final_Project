package registrationservice.store;

import org.springframework.stereotype.Component;
import registrationservice.model.Device;
import registrationservice.model.Lab;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Component
public class InMemoryRegistrationStore {

  private final Map<String, Lab> labs = new LinkedHashMap<>();
  private final Map<String, List<Device>> devicesByLab = new LinkedHashMap<>();

  public Lab saveLab(Lab lab) {
    labs.put(lab.getLabId(), lab);
    devicesByLab.putIfAbsent(lab.getLabId(), new ArrayList<>());
    return lab;
  }

  public List<Lab> getAllLabs() {
    return new ArrayList<>(labs.values());
  }

  public boolean existsLab(String labId) {
    return labs.containsKey(labId);
  }

  public Device saveDevice(String labId, Device device) {
    devicesByLab.putIfAbsent(labId, new ArrayList<>());
    devicesByLab.get(labId).add(device);
    return device;
  }

  public List<Device> getDevicesByLab(String labId) {
    return new ArrayList<>(devicesByLab.getOrDefault(labId, new ArrayList<>()));
  }

  public boolean existsDevice(String labId, String deviceId) {
    return devicesByLab.getOrDefault(labId, new ArrayList<>())
        .stream()
        .anyMatch(d -> d.getDeviceId().equals(deviceId));
  }

  public Device getDevice(String labId, String deviceId) {
    return devicesByLab.getOrDefault(labId, new ArrayList<>())
        .stream()
        .filter(d -> d.getDeviceId().equals(deviceId))
        .findFirst()
        .orElse(null);
  }
}