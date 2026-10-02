package org.personal.imtlauncher;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * i茅台启动器无障碍服务。
 *
 * 能力：按文字（含 contentDescription）查找控件并点击、
 * 判断文字是否存在、列表前滚、手势上滑、按比例坐标点击、返回。
 *
 * 服务在代码中完成配置（无需 res/xml 资源），Python 通过 pyjnius
 * 调用 getInstance() 上的方法驱动自动化流程。
 */
public class MtA11yService extends AccessibilityService {

    private static MtA11yService sInstance;

    /** Python 侧据此判断无障碍是否已授权连接 */
    public static boolean isReady() {
        return sInstance != null;
    }

    public static MtA11yService getInstance() {
        return sInstance;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        sInstance = this;

        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                | AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.flags = AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS
                | AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
                | AccessibilityServiceInfo.FLAG_REQUEST_ENHANCED_WEB_ACCESSIBILITY
                | AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS;
        info.notificationTimeout = 80;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            info.capabilities |=
                    AccessibilityServiceInfo.CAPABILITY_CAN_PERFORM_GESTURES;
        }
        setServiceInfo(info);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Python 以轮询方式驱动，无需在此处理事件
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public void onDestroy() {
        if (sInstance == this) {
            sInstance = null;
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------------
    // 对外能力（Python 通过 pyjnius 调用）
    // ------------------------------------------------------------------

    /** 页面上是否存在包含指定文字的控件 */
    public boolean textExists(String text) {
        for (AccessibilityNodeInfo root : roots()) {
            List<AccessibilityNodeInfo> hits = new ArrayList<>();
            findByText(root, text, hits);
            recycle(root);
            if (!hits.isEmpty()) {
                return true;
            }
        }
        return false;
    }

    /**
     * 页面上是否存在文字同时包含全部关键字的控件
     * （用于精确匹配 "飞天53%vol 500ml" + "带杯"）。
     */
    public boolean nodeContainsAll(String[] parts) {
        for (AccessibilityNodeInfo root : roots()) {
            AccessibilityNodeInfo hit = findByAllParts(root, parts);
            recycle(root);
            if (hit != null) {
                return true;
            }
        }
        return false;
    }

    /**
     * 扫描全部控件文字，返回匹配正则的内容，按控件在屏幕上的位置
     * 由下往上排序（右下角的开售时间优先），自动去重。
     */
    public String[] findRegexTexts(String regex) {
        Pattern pattern;
        try {
            pattern = Pattern.compile(regex);
        } catch (Exception e) {
            return new String[0];
        }
        // key=匹配文字，value=该控件底边的 Y 坐标（取最大）
        Map<String, Integer> bottomByText = new HashMap<>();
        for (AccessibilityNodeInfo root : roots()) {
            collectRegex(root, pattern, null, bottomByText);
            recycle(root);
        }
        return orderByBottom(bottomByText);
    }

    /**
     * 只在指定屏幕比例区域内扫描匹配正则的控件文字
     * （用于只读取右下角购买按钮区的开售时间）。
     */
    public String[] findRegexTextsInRegion(String regex, float minXRatio,
            float minYRatio, float maxXRatio, float maxYRatio) {
        Pattern pattern;
        try {
            pattern = Pattern.compile(regex);
        } catch (Exception e) {
            return new String[0];
        }
        Rect region = ratioRect(minXRatio, minYRatio, maxXRatio, maxYRatio);
        Map<String, Integer> bottomByText = new HashMap<>();
        for (AccessibilityNodeInfo root : roots()) {
            collectRegex(root, pattern, region, bottomByText);
            recycle(root);
        }
        return orderByBottom(bottomByText);
    }

    /** 查找并点击第一个包含指定文字的控件 */
    public boolean clickByText(String text) {
        for (AccessibilityNodeInfo root : roots()) {
            List<AccessibilityNodeInfo> hits = new ArrayList<>();
            findByText(root, text, null, hits);
            if (!hits.isEmpty()) {
                boolean ok = clickNode(hits.get(0));
                recycle(root);
                return ok;
            }
            recycle(root);
        }
        return false;
    }

    /** 只在指定屏幕比例区域内查找并点击包含指定文字的控件 */
    public boolean clickByTextInRegion(String text, float minXRatio,
            float minYRatio, float maxXRatio, float maxYRatio) {
        Rect region = ratioRect(minXRatio, minYRatio, maxXRatio, maxYRatio);
        for (AccessibilityNodeInfo root : roots()) {
            List<AccessibilityNodeInfo> hits = new ArrayList<>();
            findByText(root, text, region, hits);
            if (!hits.isEmpty()) {
                boolean ok = clickNode(hits.get(0));
                recycle(root);
                return ok;
            }
            recycle(root);
        }
        return false;
    }

    /** 查找文字同时包含全部关键字的控件并点击 */
    public boolean clickByAllParts(String[] parts) {
        for (AccessibilityNodeInfo root : roots()) {
            AccessibilityNodeInfo hit = findByAllParts(root, parts);
            if (hit != null) {
                boolean ok = clickNode(hit);
                recycle(root);
                return ok;
            }
            recycle(root);
        }
        return false;
    }

    /** 对第一个可滚动控件执行一次"前滚"（列表向下/内容上移） */
    public boolean scrollForwardOnce() {
        for (AccessibilityNodeInfo root : roots()) {
            AccessibilityNodeInfo scroller = findScrollable(root);
            if (scroller != null) {
                boolean ok = scroller.performAction(
                        AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);
                recycle(root);
                return ok;
            }
            recycle(root);
        }
        return false;
    }

    /**
     * 手势上滑（从下往上），坐标按屏幕比例给出。
     * cxRatio：横向位置；bottomRatio/topRatio：起止纵向位置。
     */
    public boolean swipeUpRatios(float cxRatio, float topRatio,
                                 float bottomRatio, long durationMs) {
        DisplayMetrics m = getResources().getDisplayMetrics();
        int x = (int) (m.widthPixels * cxRatio);
        int yTop = (int) (m.heightPixels * topRatio);
        int yBottom = (int) (m.heightPixels * bottomRatio);
        return dispatchSwipe(x, yBottom, x, yTop, durationMs);
    }

    /** 按屏幕比例点击坐标（兜底手段） */
    public boolean tapRatio(float xRatio, float yRatio) {
        DisplayMetrics m = getResources().getDisplayMetrics();
        int x = (int) (m.widthPixels * xRatio);
        int y = (int) (m.heightPixels * yRatio);
        return dispatchTap(x, y);
    }

    /** 全局返回 */
    public boolean globalBack() {
        return performGlobalAction(GLOBAL_ACTION_BACK);
    }

    // ------------------------------------------------------------------
    // 内部实现
    // ------------------------------------------------------------------

    private List<AccessibilityNodeInfo> roots() {
        List<AccessibilityNodeInfo> result = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            List<AccessibilityWindowInfo> windows = getWindows();
            if (windows != null) {
                for (AccessibilityWindowInfo window : windows) {
                    AccessibilityNodeInfo root = window.getRoot();
                    if (root != null) {
                        result.add(root);
                    }
                }
            }
        }
        if (result.isEmpty()) {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root != null) {
                result.add(root);
            }
        }
        return result;
    }

    private void findByText(AccessibilityNodeInfo node, String needle,
                            List<AccessibilityNodeInfo> out) {
        findByText(node, needle, null, out);
    }

    private void findByText(AccessibilityNodeInfo node, String needle,
                            Rect region, List<AccessibilityNodeInfo> out) {
        if (node == null || out.size() >= 5) {
            return;
        }
        if ((containsSeq(node.getText(), needle)
                || containsSeq(node.getContentDescription(), needle))
                && (region == null || centerInRegion(node, region))) {
            out.add(node);
        }
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            findByText(node.getChild(i), needle, region, out);
        }
    }

    private AccessibilityNodeInfo findByAllParts(AccessibilityNodeInfo node,
                                                 String[] parts) {
        if (node == null) {
            return null;
        }
        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        if (allContained(text, parts) || allContained(desc, parts)) {
            return node;
        }
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo hit = findByAllParts(node.getChild(i), parts);
            if (hit != null) {
                return hit;
            }
        }
        return null;
    }

    private void collectRegex(AccessibilityNodeInfo node, Pattern pattern,
                              Rect region, Map<String, Integer> out) {
        if (node == null) {
            return;
        }
        scanOne(node.getText(), node, pattern, region, out);
        scanOne(node.getContentDescription(), node, pattern, region, out);
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            collectRegex(node.getChild(i), pattern, region, out);
        }
    }

    private void scanOne(CharSequence source, AccessibilityNodeInfo node,
                         Pattern pattern, Rect region,
                         Map<String, Integer> out) {
        if (source == null) {
            return;
        }
        if (region != null && !centerInRegion(node, region)) {
            return;
        }
        Matcher matcher = pattern.matcher(source);
        Rect rect = new Rect();
        while (matcher.find()) {
            String hit = matcher.group();
            node.getBoundsInScreen(rect);
            Integer prev = out.get(hit);
            if (prev == null || rect.bottom > prev) {
                out.put(hit, rect.bottom);
            }
        }
    }

    private AccessibilityNodeInfo findScrollable(AccessibilityNodeInfo node) {
        if (node == null) {
            return null;
        }
        if (node.isScrollable()) {
            return node;
        }
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo hit = findScrollable(node.getChild(i));
            if (hit != null) {
                return hit;
            }
        }
        return null;
    }

    private boolean clickNode(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        if (node.isClickable()) {
            return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        }
        AccessibilityNodeInfo parent = node.getParent();
        int hops = 0;
        while (parent != null && hops < 6) {
            if (parent.isClickable()) {
                return parent.performAction(AccessibilityNodeInfo.ACTION_CLICK);
            }
            parent = parent.getParent();
            hops++;
        }
        // 少数控件声明了点击动作但 isClickable 为 false，最后直接尝试
        return node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
    }

    private boolean dispatchTap(int x, int y) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, 1);
        return dispatchGestureWithResult(
                new GestureDescription.Builder().addStroke(stroke).build());
    }

    private boolean dispatchSwipe(int x1, int y1, int x2, int y2,
                                  long durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);
        return dispatchGestureWithResult(
                new GestureDescription.Builder().addStroke(stroke).build());
    }

    private boolean dispatchGestureWithResult(GestureDescription gesture) {
        final CountDownLatch latch = new CountDownLatch(1);
        final boolean[] ok = new boolean[]{false};
        boolean scheduled = dispatchGesture(gesture,
                new GestureResultCallback() {
                    @Override
                    public void onCompleted(GestureDescription g) {
                        ok[0] = true;
                        latch.countDown();
                    }

                    @Override
                    public void onCancelled(GestureDescription g) {
                        ok[0] = false;
                        latch.countDown();
                    }
                }, null);
        if (!scheduled) {
            return false;
        }
        try {
            if (!latch.await(2, TimeUnit.SECONDS)) {
                return false;
            }
        } catch (InterruptedException e) {
            return false;
        }
        return ok[0];
    }

    // ------------------------------------------------------------------
    // 坐标区域工具
    // ------------------------------------------------------------------

    /** 把屏幕比例区域换算成像素矩形 */
    private Rect ratioRect(float minXRatio, float minYRatio,
                           float maxXRatio, float maxYRatio) {
        DisplayMetrics m = getResources().getDisplayMetrics();
        return new Rect(
                (int) (m.widthPixels * minXRatio),
                (int) (m.heightPixels * minYRatio),
                (int) (m.widthPixels * maxXRatio),
                (int) (m.heightPixels * maxYRatio));
    }

    /** 控件中心点是否落在区域内 */
    private static boolean centerInRegion(AccessibilityNodeInfo node, Rect region) {
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        return region.contains(rect.centerX(), rect.centerY());
    }

    /** 匹配文字按控件底边由下往上排序 */
    private static String[] orderByBottom(final Map<String, Integer> bottomByText) {
        List<String> ordered = new ArrayList<>(bottomByText.keySet());
        Collections.sort(ordered, new Comparator<String>() {
            @Override
            public int compare(String a, String b) {
                return bottomByText.get(b) - bottomByText.get(a);
            }
        });
        return ordered.toArray(new String[0]);
    }

    private static boolean containsSeq(CharSequence source, String needle) {
        return source != null && needle != null
                && source.toString().contains(needle);
    }

    private static boolean allContained(CharSequence source, String[] parts) {
        if (source == null) {
            return false;
        }
        String s = source.toString();
        for (String part : parts) {
            if (part == null || part.length() == 0 || !s.contains(part)) {
                return false;
            }
        }
        return true;
    }

    private static void recycle(AccessibilityNodeInfo root) {
        // 根节点回收即可，子节点随根一同释放
        try {
            root.recycle();
        } catch (Exception ignored) {
        }
    }
}
