import sys
from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QDialog
from PyQt6.QtGui import QPainter, QScreen, QPixmap, QColor, QPen, QBrush, QCursor
from PyQt6.QtCore import Qt, QRect, QPoint

from src.logger import info, warning, error
from src.ui.input import InputWorker


# 配置常量
HANDLE_SIZE = 8  # 调整手柄的大小

class ResizableRectItem:
    """管理一个可调整大小的矩形框"""
    def __init__(self, rect, color, on_change):
        self.rect = rect.normalized()
        self.color = color
        self.on_change_callback = on_change
        self.handles = {}
        self.handle_cursors = {}
        self.update_handles()

    def update_handles(self):
        """更新所有调整手柄的位置"""
        s = HANDLE_SIZE
        # self.handles['top'] = QRect(self.rect.left() + s, self.rect.top() - s//2, self.rect.width() - s*2, s)
        # self.handles['bottom'] = QRect(self.rect.left() + s, self.rect.bottom() - s//2, self.rect.width() - s*2, s)
        # self.handles['left'] = QRect(self.rect.left() - s//2, self.rect.top() + s, s, self.rect.height() - s*2)
        # self.handles['right'] = QRect(self.rect.right() - s//2, self.rect.top() + s, s, self.rect.height() - s*2)
        self.handles['top_left'] = QRect(self.rect.left() - s//2, self.rect.top() - s//2, s, s)
        self.handles['top_right'] = QRect(self.rect.right() - s//2, self.rect.top() - s//2, s, s)
        self.handles['bottom_left'] = QRect(self.rect.left() - s//2, self.rect.bottom() - s//2, s, s)
        self.handles['bottom_right'] = QRect(self.rect.right() - s//2, self.rect.bottom() - s//2, s, s)
        self.handles['center'] = QRect(self.rect.center().x() - s//2, self.rect.center().y() - s//2, s, s)

        # 为每个手柄设置光标形状
        self.handle_cursors = {
            'top': Qt.CursorShape.SizeVerCursor, 'bottom': Qt.CursorShape.SizeVerCursor,
            'left': Qt.CursorShape.SizeHorCursor, 'right': Qt.CursorShape.SizeHorCursor,
            'top_left': Qt.CursorShape.SizeFDiagCursor, 'bottom_right': Qt.CursorShape.SizeFDiagCursor,
            'top_right': Qt.CursorShape.SizeBDiagCursor, 'bottom_left': Qt.CursorShape.SizeBDiagCursor,
            'center': Qt.CursorShape.SizeAllCursor
        }

    def draw(self, painter: QPainter):
        """绘制矩形框和手柄"""
        painter.setPen(QPen(self.color, 1, Qt.PenStyle.SolidLine))
        
        # 绘制半透明填充
        fill_color = QColor(self.color)
        fill_color.setAlpha(80)
        painter.setBrush(QBrush(fill_color))
        painter.drawRect(self.rect)

        # 绘制调整手柄
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        for handle in self.handles.values():
            painter.drawRect(handle)

    def hit_test(self, pos: QPoint):
        """测试鼠标位置是否在任何手柄上"""
        for name, rect in self.handles.items():
            if rect.contains(pos):
                return name, self.handle_cursors.get(name, Qt.CursorShape.ArrowCursor)
        if self.rect.contains(pos):
            return 'center', Qt.CursorShape.SizeAllCursor
        return None, Qt.CursorShape.ArrowCursor

    def update_geometry(self, press_pos: QPoint, current_pos: QPoint, handle_name: str):
        """根据拖动的手柄更新矩形几何信息"""
        delta = current_pos - press_pos
        
        if handle_name == 'center':
            self.rect.translate(delta)
        elif 'top' in handle_name:
            self.rect.setTop(self.rect.top() + delta.y())
        elif 'bottom' in handle_name:
            self.rect.setBottom(self.rect.bottom() + delta.y())
        
        if 'left' in handle_name:
            self.rect.setLeft(self.rect.left() + delta.x())
        elif 'right' in handle_name:
            self.rect.setRight(self.rect.right() + delta.x())

        self.rect = self.rect.normalized()
        self.update_handles()
        self.on_change_callback()


class CaptureRegionWindow(QDialog):
    """一个支持区域选择的截屏窗口"""

    def __init__(self, config: dict, input: InputWorker, parent=None):
        super().__init__(parent)
        self.config = config
        input.key_combo_pressed.connect(self._process_key_combo)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint 
          | Qt.WindowType.WindowStaysOnTopHint
          | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.screenshot_pixmap: QPixmap = None
        self.rect_items = []
        self.result = None

        # 状态变量
        self.is_drawing = False
        self.start_pos = None
        self.current_pos = None
        self.current_color = None

        self.active_item = None
        self.active_handle = None
        self.press_pos_for_drag = None

        self.screenshot_at_saving = None

        self.btns: list[QPushButton] = []
        self.cancel_btn: QPushButton = None
        self.save_btn: QPushButton = None

    def _setup_ui(self):
        """根据配置创建UI元素"""
        for btn in self.btns:
            btn.setParent(None)
            btn.deleteLater()
        self.btns.clear()
        if self.cancel_btn:
            self.cancel_btn.setParent(None)
            self.cancel_btn.deleteLater()
            self.cancel_btn = None
        if self.save_btn:
            self.save_btn.setParent(None)
            self.save_btn.deleteLater()
            self.save_btn = None

        screen_size = self.screen().size()
        def get_abs_pos(rel_pos):
            x, y = rel_pos
            return int(screen_size.width() * x), int(screen_size.height() * y)

        for btn_config in self.config.get('annotation_buttons', []):
            btn = QPushButton(btn_config['text'], self)
            btn.move(*get_abs_pos(btn_config['pos']))
            btn.setFixedHeight(btn_config['size'])
            btn.setStyleSheet(f"background-color: {btn_config['color']}; color: white; "
                              f"border-radius: 4px; padding: 8px; font-size: {btn_config['size'] - 16}px;")
            color = btn_config['color']
            btn.clicked.connect(lambda _, c=color: self._on_annotation_button_clicked(c))
            self.btns.append(btn)

        cancel_cfg = self.config.get('control_buttons', {}).get('cancel')
        if cancel_cfg:
            cancel_btn = QPushButton(cancel_cfg['text'], self)
            cancel_btn.move(*get_abs_pos(cancel_cfg['pos']))
            cancel_btn.setFixedHeight(cancel_cfg['size'])
            cancel_btn.setStyleSheet(f"background-color: {cancel_cfg['color']}; color: black; "
                                     f"border-radius: 4px; padding: 8px; font-size: {cancel_cfg['size'] - 16}px;")
            cancel_btn.clicked.connect(self._cancel)
            self.cancel_btn = cancel_btn

        save_cfg = self.config.get('control_buttons', {}).get('save')
        if save_cfg:
            save_btn = QPushButton(save_cfg['text'], self)
            save_btn.move(*get_abs_pos(save_cfg['pos']))
            save_btn.setFixedHeight(save_cfg['size'])
            save_btn.setStyleSheet(f"background-color: {save_cfg['color']}; color: black; "
                                   f"border-radius: 4px; padding: 8px; font-size: {save_cfg['size'] - 16}px;")
            save_btn.clicked.connect(self._save)
            self.save_btn = save_btn

    def capture_and_show(self):
        """捕获全屏并显示窗口，以模态方式运行"""
        # 修改为捕获鼠标所在屏幕
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if not screen: return None
        self.screenshot_pixmap = screen.grabWindow(0)
        info(f"Start to capture region at screen {tuple(screen.geometry().getRect())} with devicePixelRatio {screen.devicePixelRatio()}")
        self.screenshot_pixmap.setDevicePixelRatio(screen.devicePixelRatio())
        self.setGeometry(screen.geometry())
        self._setup_ui()
        self.exec()
        return self.result

    def paintEvent(self, event):
        if not self.screenshot_pixmap:
            return

        painter = QPainter(self)
        # 1. 绘制截屏背景
        painter.drawPixmap(self.rect(), self.screenshot_pixmap)

        # 2. 绘制半透明遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

        def scale_rect(rect: QRect) -> QRect:
            dpr = self.screen().devicePixelRatio()
            return QRect(
                int(rect.x() * dpr),
                int(rect.y() * dpr),
                int(rect.width() * dpr),
                int(rect.height() * dpr)
            )
        
        # 3. 绘制所有已创建的矩形区域（使其恢复明亮）
        for item in self.rect_items: 
            painter.drawPixmap(item.rect, self.screenshot_pixmap, scale_rect(item.rect))
            item.draw(painter)

        # 4. 如果正在绘制新矩形，绘制它
        if self.is_drawing and self.start_pos and self.current_pos:
            drawing_rect = QRect(self.start_pos, self.current_pos).normalized()
            # 绘制明亮区域
            painter.drawPixmap(drawing_rect, self.screenshot_pixmap, scale_rect(drawing_rect))
            # 绘制边框
            painter.setPen(QPen(QColor(self.current_color), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(drawing_rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self.press_pos_for_drag = event.pos()
            
            # 首先检查是否点击了现有矩形的手柄
            for item in reversed(self.rect_items):
                handle, cursor = item.hit_test(event.pos())
                if handle:
                    self.active_item = item
                    self.active_handle = handle
                    self.setCursor(cursor)
                    return

            # 如果没有点击手柄，且已选择颜色，则开始绘制新矩形
            if self.current_color:
                self.is_drawing = True
                self.start_pos = event.pos()
                self.current_pos = event.pos()

    def mouseMoveEvent(self, event):
        # 如果正在操作现有矩形
        if self.active_item and self.active_handle:
            self.active_item.update_geometry(self.press_pos_for_drag, event.pos(), self.active_handle)
            self.press_pos_for_drag = event.pos() # 更新拖动起始点
            return

        # 如果正在绘制新矩形
        if self.is_drawing:
            self.current_pos = event.pos()
            self.update()
        else:
            # 否则，更新光标形状
            cursor = Qt.CursorShape.ArrowCursor
            for item in reversed(self.rect_items):
                _, new_cursor = item.hit_test(event.pos())
                if new_cursor != Qt.CursorShape.ArrowCursor:
                    cursor = new_cursor
                    break
            self.setCursor(cursor)


    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 结束操作现有矩形
            if self.active_item:
                self.active_item = None
                self.active_handle = None
                self.setCursor(Qt.CursorShape.ArrowCursor)

            # 结束绘制新矩形
            elif self.is_drawing and self.start_pos:
                final_rect = QRect(self.start_pos, event.pos()).normalized()
                if final_rect.width() > 5 and final_rect.height() > 5:
                    new_item = ResizableRectItem(final_rect, QColor(self.current_color), self.update)
                    self.rect_items.append(new_item)
                
                self.is_drawing = False
                self.start_pos = None
                self.current_pos = None
                self.current_color = None # 重置颜色选择，需要用户再次点击按钮
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()

    def _process_key_combo(self, keys: tuple[int]):
        if not self.isVisible():
            return
        if 'enter' in keys:
            self._save()
        elif 'esc' in keys:
            self._cancel()
    
    def _on_annotation_button_clicked(self, color: str):
        self.current_color = color
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _save(self):
        screen = self.screen()
        self.screenshot_at_saving = screen.grabWindow(0)
        self.result = [
            {
                'rect': item.rect.getRect(), # (x, y, width, height)
                'color': item.color.name().lower()   # '#rrggbb'
            }
            for item in self.rect_items
        ]
        # 计算缩放比例和偏移
        offset_x = screen.geometry().x()
        offset_y = screen.geometry().y()
        scale = self.screen().devicePixelRatio()
        for r in self.result:
            x, y, w, h = r['rect']
            r['rect'] = (
                int(x * scale) + offset_x,
                int(y * scale) + offset_y,
                int(w * scale),
                int(h * scale)
            )
            info(f"CaptureRegionWindow: Saved rect {(x, y, w, h)} -> {r['rect']} with color {r['color']}")
        self.close()

    def _cancel(self):
        self.result = None
        self.close()



# --- 使用示例 ---
if __name__ == '__main__':
    app = QApplication(sys.argv)

    # 定义窗口配置
    from PIL import ImageGrab
    sw, sh = ImageGrab.grab().size
    SCREENSHOT_WINDOW_CONFIG = {
        'annotation_buttons': [
            {'pos': (int(sw * 0.8), int(sh * 0.1)), 'size': 32, 'color': "#a84747", 'text': '点我并框出 血条 的区域'},
            {'pos': (int(sw * 0.8), int(sh * 0.2)), 'size': 32, 'color': "#686435", 'text': '点我并框出 DAY I 图标 的区域'},
        ],
        'control_buttons': {
            'cancel':   {'pos': (int(sw * 0.8), int(sh * 0.5)), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
            'save':     {'pos': (int(sw * 0.8), int(sh * 0.6)), 'size': 50, 'color': "#ffffff", 'text': '保存'},
        }
    }

    # 注意：直接运行脚本会立即开始截屏
    # 1. 实例化窗口 (此时是隐藏的)
    screenshot_tool = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG)
    
    # 2. 调用 capture_and_show() 来开始截屏流程
    #    该函数会阻塞，直到用户点击 "保存" 或 "取消"
    captured_data = screenshot_tool.capture_and_show()

    # 3. 处理返回结果
    if captured_data:
        print("保存成功，捕获的矩形框信息:")
        for i, data in enumerate(captured_data):
            print(f"  矩形 {i+1}:")
            print(f"    坐标和尺寸 (x, y, w, h): {data['rect']}")
            print(f"    颜色: {data['color']}")
    else:
        print("操作已取消。")
    
    # app.exec() 在 capture_and_show 内部已经调用，这里不需要再次调用
    # sys.exit() is often called implicitly when the app loop ends.