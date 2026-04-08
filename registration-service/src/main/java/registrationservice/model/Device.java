package registrationservice.model;

import java.util.List;

public class Device {
  private String deviceId;
  private String labId;
  private String displayName;
  private String type;
  private List<String> modules;
  private int capacity;
  private int inUse;

  public Device() {
  }

  public Device(String deviceId, String labId, String displayName, String type,
      List<String> modules, int capacity, int inUse) {
    this.deviceId = deviceId;
    this.labId = labId;
    this.displayName = displayName;
    this.type = type;
    this.modules = modules;
    this.capacity = capacity;
    this.inUse = inUse;
  }

  public String getDeviceId() {
    return deviceId;
  }

  public void setDeviceId(String deviceId) {
    this.deviceId = deviceId;
  }

  public String getLabId() {
    return labId;
  }

  public void setLabId(String labId) {
    this.labId = labId;
  }

  public String getDisplayName() {
    return displayName;
  }

  public void setDisplayName(String displayName) {
    this.displayName = displayName;
  }

  public String getType() {
    return type;
  }

  public void setType(String type) {
    this.type = type;
  }

  public List<String> getModules() {
    return modules;
  }

  public void setModules(List<String> modules) {
    this.modules = modules;
  }

  public int getCapacity() {
    return capacity;
  }

  public void setCapacity(int capacity) {
    this.capacity = capacity;
  }

  public int getInUse() {
    return inUse;
  }

  public void setInUse(int inUse) {
    this.inUse = inUse;
  }

  public int getAvailable() {
    return capacity - inUse;
  }
}