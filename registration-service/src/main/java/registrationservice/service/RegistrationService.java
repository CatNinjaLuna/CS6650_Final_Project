package registrationservice.service;

import org.springframework.stereotype.Service;
import registrationservice.model.CreateDeviceRequest;
import registrationservice.model.CreateLabRequest;
import registrationservice.model.Device;
import registrationservice.model.Lab;
import registrationservice.model.LabWithDevices;
import registrationservice.store.InMemoryRegistrationStore;

import java.util.ArrayList;
import java.util.List;

@Service
public class RegistrationService {

  private final InMemoryRegistrationStore store;

  public RegistrationService(InMemoryRegistrationStore store) {
    this.store = store;
  }

  public Lab createLab(CreateLabRequest request) {
    if (request.getLabId() == null || request.getLabId().isBlank()) {
      throw new IllegalArgumentException("labId is required");
    }
    if (request.getName() == null || request.getName().isBlank()) {
      throw new IllegalArgumentException("name is required");
    }
    if (store.existsLab(request.getLabId())) {
      throw new IllegalArgumentException("lab already exists: " + request.getLabId());
    }

    Lab lab = new Lab(
        request.getLabId(),
        request.getName(),
        request.getLocation()
    );

    return store.saveLab(lab);
  }

  public List<Lab> getAllLabs() {
    return store.getAllLabs();
  }

  public Device createDevice(String labId, CreateDeviceRequest request) {
    if (!store.existsLab(labId)) {
      throw new IllegalArgumentException("lab does not exist: " + labId);
    }
    if (request.getDeviceId() == null || request.getDeviceId().isBlank()) {
      throw new IllegalArgumentException("deviceId is required");
    }
    if (request.getDisplayName() == null || request.getDisplayName().isBlank()) {
      throw new IllegalArgumentException("displayName is required");
    }
    if (request.getType() == null || request.getType().isBlank()) {
      throw new IllegalArgumentException("type is required");
    }
    if (request.getCapacity() <= 0) {
      throw new IllegalArgumentException("capacity must be > 0");
    }
    if (store.existsDevice(labId, request.getDeviceId())) {
      throw new IllegalArgumentException("device already exists in lab: " + request.getDeviceId());
    }

    Device device = new Device(
        request.getDeviceId(),
        labId,
        request.getDisplayName(),
        request.getType(),
        request.getModules(),
        request.getCapacity(),
        0
    );

    return store.saveDevice(labId, device);
  }

  public List<Device> getDevicesByLab(String labId) {
    if (!store.existsLab(labId)) {
      throw new IllegalArgumentException("lab does not exist: " + labId);
    }
    return store.getDevicesByLab(labId);
  }

  public Device getDevice(String labId, String deviceId) {
    if (!store.existsLab(labId)) {
      throw new IllegalArgumentException("lab does not exist: " + labId);
    }

    Device device = store.getDevice(labId, deviceId);
    if (device == null) {
      throw new IllegalArgumentException("device does not exist in lab: " + deviceId);
    }

    return device;
  }

  public List<LabWithDevices> getAllLabsWithDevices() {
    List<LabWithDevices> result = new ArrayList<>();

    for (Lab lab : store.getAllLabs()) {
      result.add(new LabWithDevices(
          lab.getLabId(),
          lab.getName(),
          lab.getLocation(),
          store.getDevicesByLab(lab.getLabId())
      ));
    }

    return result;
  }
}