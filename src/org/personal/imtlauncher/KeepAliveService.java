package org.personal.imtlauncher;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * 保活前台服务。
 *
 * 为什么需要：抢购助手切到后台后，部分 ROM（尤其 ColorOS/EMUI）会把
 * 进程冻结，FlowWorker 线程停摆。日志表现为“到达拉起时刻”晚几十秒、
 * 详情页几十秒不刷新。前台服务 + PARTIAL_WAKE_LOCK 让进程在定时抢购
 * 期间保持可调度；流程结束/取消时由 Python 侧 stopService 关闭。
 */
public class KeepAliveService extends Service {

    private static final String CHANNEL_ID = "imt_keepalive";
    private static final int NOTIFICATION_ID = 1001;

    private PowerManager.WakeLock wakeLock;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification());
        try {
            PowerManager manager =
                    (PowerManager) getSystemService(POWER_SERVICE);
            if (manager != null) {
                wakeLock = manager.newWakeLock(
                        PowerManager.PARTIAL_WAKE_LOCK, "imt:flow");
                wakeLock.setReferenceCounted(false);
                wakeLock.acquire();
            }
        } catch (Exception ignored) {
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) {
                wakeLock.release();
            }
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager =
                (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "\u62a2\u8d2d\u52a9\u624b\u8fd0\u884c\u4e2d",
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(
                "\u5b9a\u65f6\u62a2\u8d2d\u671f\u95f4\u4fdd\u6301\u540e\u53f0\u8fd0\u884c");
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }
        builder.setContentTitle("\u62a2\u8d2d\u52a9\u624b")
                .setContentText(
                        "\u5b9a\u65f6\u62a2\u8d2d\u8fd0\u884c\u4e2d")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setOngoing(true);
        return builder.build();
    }
}
