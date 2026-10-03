package org.personal.imtlauncher;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
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
 * 服务配置（事件类型、canPerformGestures 手势能力等）由
 * res/xml/imt_a11y_config.xml 经清单 meta-data 提供；Python 通过
 * pyjnius 调用 getInstance() 上的方法驱动自动化流程。
 */
public class MtA11yService extends AccessibilityService {

    private static MtA11yService sInstance;

    /** 拟人化手势随机源（落点抖动、时长、轨迹） */
    private final Random mRandom = new Random();

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
        // 服务配置（事件类型、标志、canPerformGestures 手势能力等）由
        // res/xml/imt_a11y_config.xml 经清单 meta-data 提供。
        // 不要在此调用 setServiceInfo 覆盖：程序构造的配置无法声明手势
        // 能力（capabilities 为私有字段、setCapabilities 为隐藏 API），
        // 一旦覆盖，XML 中声明的 canPerformGestures 会丢失。
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
     * 统计给定文字中有多少个能在当前页面找到（去重计数）。
     * 用于确认购页面：顶部 "全部/经典/精品" 等分类标签同时出现
     * 多个，才判定确实进入了购页面。
     */
    public int countDistinctTexts(String[] texts) {
        if (texts == null) {
            return 0;
        }
        int count = 0;
        for (String text : texts) {
            if (text != null && textExists(text)) {
                count++;
            }
        }
        return count;
    }

    /**
     * 页面上是否存在"可见的"包含指定文字的控件：
     * 除文字匹配外，还要求控件在屏幕上有真实尺寸（宽高 > 1）。
     * i茅台底部标签的文字节点是 bounds=[0,0][0,0] 的不可见节点，
     * 不能用普通 textExists 判断页面是否真的渲染完成。
     */
    public boolean textExistsVisible(String text) {
        for (AccessibilityNodeInfo root : roots()) {
            List<AccessibilityNodeInfo> hits = new ArrayList<>();
            findVisibleByText(root, text, null, hits);
            recycle(root);
            if (!hits.isEmpty()) {
                return true;
            }
        }
        return false;
    }

    /** 统计给定文字中有多少个以"可见控件"形式存在（去重计数） */
    public int countDistinctVisibleTexts(String[] texts) {
        if (texts == null) {
            return 0;
        }
        int count = 0;
        for (String text : texts) {
            if (text != null && textExistsVisible(text)) {
                count++;
            }
        }
        return count;
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
        DisplayMetrics m = realMetrics();
        int x = (int) (m.widthPixels * cxRatio);
        int yTop = (int) (m.heightPixels * topRatio);
        int yBottom = (int) (m.heightPixels * bottomRatio);
        return dispatchSwipe(x, yBottom, x, yTop, durationMs);
    }

    /** 按屏幕比例点击坐标（兜底手段） */
    public boolean tapRatio(float xRatio, float yRatio) {
        DisplayMetrics m = realMetrics();
        int x = (int) (m.widthPixels * xRatio);
        int y = (int) (m.heightPixels * yRatio);
        return dispatchTap(x, y);
    }

    /**
     * 拟人化点击：落点在 jitterRatio 范围内小幅随机、按压时长随机
     * （60~140ms）、按压停留期间手指有 1~5px 轻微位移。
     * jitterRatio 按屏幕比例给出（如 0.01 ≈ 10px）。
     */
    public boolean tapRatioHuman(float xRatio, float yRatio,
                                 float jitterRatio) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        DisplayMetrics m = realMetrics();
        float jitterX = jitterRatio * m.widthPixels;
        float jitterY = jitterRatio * m.heightPixels;
        float x = clamp(
                m.widthPixels * xRatio
                        + (mRandom.nextFloat() * 2f - 1f) * jitterX,
                0, m.widthPixels - 1);
        float y = clamp(
                m.heightPixels * yRatio
                        + (mRandom.nextFloat() * 2f - 1f) * jitterY,
                0, m.heightPixels - 1);

        Path path = new Path();
        path.moveTo(x, y);
        float driftX = (mRandom.nextFloat() * 2f - 1f) * 5f;
        float driftY = (mRandom.nextFloat() * 2f - 1f) * 5f;
        path.lineTo(x + driftX, y + driftY);

        long holdMs = 60L + mRandom.nextInt(81); // 60~140ms
        return dispatchPath(path, holdMs);
    }

    /**
     * 按 getevent 原始触摸坐标直接点击（配置里直接填原始值，无需
     * 人工换算比例）。rawX/rawY 为 getevent 上报的
     * ABS_MT_POSITION_X / ABS_MT_POSITION_Y 值；rawMaxX/rawMaxY
     * 为 getevent -lp 给出的触摸屏原始坐标最大值（本机 5399/11999）。
     */
    public boolean tapRawHuman(int rawX, int rawY,
                               int rawMaxX, int rawMaxY,
                               float jitterRatio) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        if (rawMaxX <= 0 || rawMaxY <= 0) {
            return false;
        }
        float xRatio = (float) rawX / (float) rawMaxX;
        float yRatio = (float) rawY / (float) rawMaxY;
        return tapRatioHuman(xRatio, yRatio, jitterRatio);
    }

    /**
     * 拟人化上滑：横向基准位置小幅随机、轨迹分 8 段逐点抖动、
     * 纵向按 smoothstep 加减速（非匀速）、整体时长在
     * minDurationMs~maxDurationMs 间随机。
     */
    public boolean swipeUpRatiosHuman(float cxRatio, float topRatio,
                                      float bottomRatio,
                                      long minDurationMs,
                                      long maxDurationMs,
                                      float jitterRatio) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        DisplayMetrics m = realMetrics();
        float jitter = jitterRatio * m.widthPixels;
        float baseX = m.widthPixels * cxRatio;
        float yBottom = m.heightPixels * bottomRatio;
        float yTop = m.heightPixels * topRatio;

        Path path = new Path();
        float startX = baseX + (mRandom.nextFloat() * 2f - 1f) * jitter;
        path.moveTo(startX, yBottom);
        final int steps = 8;
        for (int i = 1; i <= steps; i++) {
            float frac = i / (float) steps;
            float s = frac * frac * (3f - 2f * frac); // smoothstep
            float y = yBottom + (yTop - yBottom) * s;
            float x = baseX + (mRandom.nextFloat() * 2f - 1f) * jitter;
            path.lineTo(x, y);
        }

        long durationMs = minDurationMs;
        long span = maxDurationMs - minDurationMs;
        if (span > 0) {
            durationMs += mRandom.nextInt((int) span + 1);
        }
        return dispatchPath(path, durationMs);
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

    /** 同 findByText，但额外要求控件有真实可见尺寸（排除 0x0 节点） */
    private void findVisibleByText(AccessibilityNodeInfo node, String needle,
                                   Rect region,
                                   List<AccessibilityNodeInfo> out) {
        if (node == null || out.size() >= 5) {
            return;
        }
        if ((containsSeq(node.getText(), needle)
                || containsSeq(node.getContentDescription(), needle))
                && hasRealBounds(node)
                && (region == null || centerInRegion(node, region))) {
            out.add(node);
        }
        int vcount = node.getChildCount();
        for (int i = 0; i < vcount; i++) {
            findVisibleByText(node.getChild(i), needle, region, out);
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
        return dispatchPath(path, 1);
    }

    private boolean dispatchSwipe(int x1, int y1, int x2, int y2,
                                  long durationMs) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false;
        }
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        return dispatchPath(path, durationMs);
    }

    /** 按给定路径与时长派发手势并等待结果 */
    private boolean dispatchPath(Path path, long durationMs) {
        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);
        return dispatchGestureWithResult(
                new GestureDescription.Builder().addStroke(stroke).build());
    }

    private static float clamp(float v, float lo, float hi) {
        return v < lo ? lo : (v > hi ? hi : v);
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

    /**
     * 真实屏幕尺寸（含状态栏、导航栏）。
     * 注意：dispatchGesture 坐标与 getBoundsInScreen 均按全屏坐标；
     * getResources().getDisplayMetrics() 在非全屏窗口下只给 APP 可用区
     * （实测 1080x2161，物理屏 1080x2400），用它换算会让底部按钮区域
     * 整体上移、兜底点击落空。
     */
    private DisplayMetrics realMetrics() {
        DisplayMetrics m = new DisplayMetrics();
        WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        Display display = wm.getDefaultDisplay();
        display.getRealMetrics(m);
        return m;
    }

    /** 把屏幕比例区域换算成像素矩形 */
    private Rect ratioRect(float minXRatio, float minYRatio,
                           float maxXRatio, float maxYRatio) {
        DisplayMetrics m = realMetrics();
        return new Rect(
                (int) (m.widthPixels * minXRatio),
                (int) (m.heightPixels * minYRatio),
                (int) (m.widthPixels * maxXRatio),
                (int) (m.heightPixels * maxYRatio));
    }

    /** 控件是否在屏幕上有真实可见尺寸（排除 bounds 0x0 的占位节点） */
    private static boolean hasRealBounds(AccessibilityNodeInfo node) {
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        return rect.width() > 1 && rect.height() > 1;
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
